"""Infraestrutura no painel da plataforma (só leitura): gasto do mês na AWS,
a instância e o banco do Lightsail (só os do .env: LIGHTSAIL_INSTANCIA e
LIGHTSAIL_BANCO), a máquina, os bancos MySQL e o bucket de arquivos.

As credenciais da AWS são as de um usuário IAM só de leitura (AWS_ACCESS_KEY_ID
e AWS_SECRET_ACCESS_KEY no .env; o Lightsail não aceita role IAM). O que vem
da AWS fica guardado num arquivo (o mesmo para os dois workers), cada parte
com a sua validade: o Cost Explorer cobra US$ 0,01 por consulta e só atualiza
algumas vezes por dia; as métricas do Lightsail são de graça e mudam sempre."""

import json
import os
import shutil
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.central import models as m
from app.core import aws
from app.core.config import get_settings
from app.core.tempo import agora

VALIDADE_CUSTOS = 12 * 3600
VALIDADE_LIGHTSAIL = 5 * 60
VALIDADE_BUCKET = 3600  # o S3 mede uma vez por dia
VALIDADE_COM_ERRO = 5 * 60  # credencial ou permissão recém-corrigida aparece logo
INTERVALO_MINIMO = 10 * 60  # o "Atualizar" consulta a AWS no máximo a cada 10 min
SERVICOS = ("marceloimob", "nginx")
_SISTEMA = {"information_schema", "mysql", "performance_schema", "sys"}


def _cliente(servico: str, regiao: str):
    """Cliente boto3 (os testes trocam por um falso)."""
    return aws.cliente(servico, regiao)


def _explicar(e: Exception) -> str:
    nome = type(e).__name__
    if isinstance(e, ImportError):
        return "Biblioteca boto3 não instalada (pip install -r requirements.txt)."
    if nome in ("NoCredentialsError", "PartialCredentialsError"):
        return "Sem credenciais da AWS: informe AWS_ACCESS_KEY_ID e AWS_SECRET_ACCESS_KEY no .env (veja o README)."
    codigo = getattr(e, "response", {}).get("Error", {}).get("Code", "")
    if codigo in ("AccessDenied", "AccessDeniedException", "UnauthorizedOperation"):
        return f"Sem permissão na AWS ({codigo}): confira a política do usuário IAM (veja o README)."
    if codigo in ("InvalidClientTokenId", "SignatureDoesNotMatch", "UnrecognizedClientException"):
        return "A chave da AWS no .env foi recusada: confira AWS_ACCESS_KEY_ID e AWS_SECRET_ACCESS_KEY."
    if codigo == "DataUnavailableException":
        return "A AWS ainda não tem dados de custo desta conta (o Cost Explorer leva até 24 h)."
    if codigo in ("NotFoundException", "DoesNotExist"):
        return f"Não encontrado no Lightsail ({get_settings().aws_regiao}): confira o nome no .env."
    return f"{nome}: {str(e)[:200]}"


# ------------------------------------------------------------------ AWS


def _valor(metricas: dict) -> float:
    return float(metricas["UnblendedCost"]["Amount"])


def _custos() -> dict:
    """Gasto do mês (por serviço), do mês passado e a previsão do fechamento."""
    ce = _cliente("ce", "us-east-1")
    hoje = datetime.now(timezone.utc).date()  # o Cost Explorer conta em UTC
    inicio = hoje.replace(day=1)
    anterior = (inicio - timedelta(days=1)).replace(day=1)
    proximo = (inicio + timedelta(days=32)).replace(day=1)
    r = ce.get_cost_and_usage(
        TimePeriod={"Start": anterior.isoformat(), "End": (hoje + timedelta(days=1)).isoformat()},
        Granularity="MONTHLY", Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )  # fmt: skip
    meses = {p["TimePeriod"]["Start"]: p.get("Groups", []) for p in r["ResultsByTime"]}
    atual = meses.get(inicio.isoformat(), [])
    servicos = sorted(
        ({"nome": g["Keys"][0], "valor": _valor(g["Metrics"])} for g in atual),
        key=lambda s: -s["valor"],
    )
    total = sum(s["valor"] for s in servicos)
    moeda = next((g["Metrics"]["UnblendedCost"]["Unit"] for g in atual), "USD")
    previsao = None
    try:
        f = ce.get_cost_forecast(
            TimePeriod={"Start": hoje.isoformat(), "End": proximo.isoformat()},
            Granularity="MONTHLY", Metric="UNBLENDED_COST",
        )  # fmt: skip
        # O que falta do mês, somado ao que já foi gasto (como no console).
        previsao = total + float(f["Total"]["Amount"])
    except Exception:  # noqa: BLE001 - sem histórico suficiente: fica sem previsão
        pass
    return {
        "mes": inicio.isoformat(),
        "total": total,
        "moeda": moeda,
        "servicos": [s for s in servicos if s["valor"] >= 0.005],
        "anterior": sum(_valor(g["Metrics"]) for g in meses.get(anterior.isoformat(), [])),
        "previsao": previsao,
    }


def _bucket(nome: str) -> dict:
    """Tamanho e número de arquivos (métricas diárias do S3 no CloudWatch)."""
    try:
        local = _cliente("s3", "us-east-1").get_bucket_location(Bucket=nome)
        regiao = local.get("LocationConstraint") or "us-east-1"
    except Exception:  # noqa: BLE001 - sem s3:GetBucketLocation, tenta a região padrão
        regiao = "us-east-1"
    cw = _cliente("cloudwatch", regiao)
    fim = datetime.now(timezone.utc)

    def ultima(metrica: str, tipo: str) -> float | None:
        pontos = cw.get_metric_statistics(
            Namespace="AWS/S3", MetricName=metrica, Period=86400, Statistics=["Average"],
            Dimensions=[{"Name": "BucketName", "Value": nome}, {"Name": "StorageType", "Value": tipo}],
            StartTime=fim - timedelta(days=3), EndTime=fim,
        )["Datapoints"]  # fmt: skip
        return max(pontos, key=lambda p: p["Timestamp"])["Average"] if pontos else None

    return {
        "nome": nome,
        "regiao": regiao,
        "bytes": ultima("BucketSizeBytes", "StandardStorage"),
        "arquivos": ultima("NumberOfObjects", "AllStorageTypes"),
    }


def _metrica(lightsail, operacao: str, campo: str, nome: str, metrica: str, unidade: str,
             estatistica: str = "Average", horas: int = 1) -> float | None:
    """Último ponto (de 5 em 5 min) de uma métrica do Lightsail."""
    fim = datetime.now(timezone.utc)
    pontos = getattr(lightsail, operacao)(
        **{campo: nome}, metricName=metrica, period=300, unit=unidade, statistics=[estatistica],
        startTime=fim - timedelta(hours=horas), endTime=fim,
    )["metricData"]  # fmt: skip
    return max(pontos, key=lambda p: p["timestamp"])[estatistica.lower()] if pontos else None


def _preco(bundles: list[dict], bundle_id: str) -> float | None:
    return next((b["price"] for b in bundles if b["bundleId"] == bundle_id), None)


def _instancia() -> dict:
    """A instância do Lightsail que roda este servidor: plano, IP e métricas."""
    s = get_settings()
    ls = _cliente("lightsail", s.aws_regiao)
    i = ls.get_instance(instanceName=s.lightsail_instancia)["instance"]
    hw = i.get("hardware", {})
    metrica = lambda nome, unidade, est="Average": _metrica(  # noqa: E731
        ls, "get_instance_metric_data", "instanceName", i["name"], nome, unidade, est)
    return {
        "nome": i["name"],
        "estado": i["state"]["name"],
        "ip": i.get("publicIpAddress", ""),
        "ip_fixo": i.get("isStaticIp", False),
        "zona": i["location"]["availabilityZone"],
        "sistema": i.get("blueprintName", ""),
        "plano": i["bundleId"],
        "preco": _preco(ls.get_bundles(includeInactive=True)["bundles"], i["bundleId"]),
        "cpus": hw.get("cpuCount"),
        "ram_gb": hw.get("ramSizeInGb"),
        "disco_gb": sum(d.get("sizeInGb", 0) for d in hw.get("disks", [])),
        "cpu": metrica("CPUUtilization", "Percent"),
        "burst": metrica("BurstCapacityPercentage", "Percent"),
        "falhas": metrica("StatusCheckFailed", "Count", "Sum"),
    }


def _banco_lightsail() -> dict:
    """O banco gerenciado do Lightsail: plano, estado, backup e métricas."""
    s = get_settings()
    ls = _cliente("lightsail", s.aws_regiao)
    b = ls.get_relational_database(relationalDatabaseName=s.lightsail_banco)["relationalDatabase"]
    hw = b.get("hardware", {})
    metrica = lambda nome, unidade: _metrica(  # noqa: E731
        ls, "get_relational_database_metric_data", "relationalDatabaseName", b["name"], nome, unidade)
    bundles = ls.get_relational_database_bundles(includeInactive=True)["bundles"]
    restauravel = b.get("latestRestorableTime")
    return {
        "nome": b["name"],
        "estado": b["state"],
        "motor": f"{b.get('engine', '')} {b.get('engineVersion', '')}".strip(),
        "endereco": b.get("masterEndpoint", {}).get("address", ""),
        "zona": b["location"]["availabilityZone"],
        "plano": b["relationalDatabaseBundleId"],
        "preco": _preco(bundles, b["relationalDatabaseBundleId"]),
        "cpus": hw.get("cpuCount"),
        "ram_gb": hw.get("ramSizeInGb"),
        "disco": (hw.get("diskSizeInGb") or 0) * 1024**3,
        "backup": b.get("backupRetentionEnabled", False),
        "restauravel": restauravel.astimezone(ZoneInfo(s.fuso_horario)).strftime("%d/%m %H:%M") if restauravel else "",
        "publico": b.get("publiclyAccessible", False),
        "cpu": metrica("CPUUtilization", "Percent"),
        "conexoes": metrica("DatabaseConnections", "Count"),
        "livre": metrica("FreeStorageSpace", "Bytes"),
        "memoria_livre": metrica("FreeableMemory", "Bytes"),
    }


PARTES = {
    "custos": (VALIDADE_CUSTOS, lambda: _custos()),
    "instancia": (VALIDADE_LIGHTSAIL, lambda: _instancia()),
    "banco": (VALIDADE_LIGHTSAIL, lambda: _banco_lightsail()),
    "bucket": (VALIDADE_BUCKET, lambda: _bucket(get_settings().aws_bucket)),
}


def _arquivo() -> Path:
    return Path(get_settings().infra_cache)


def _ler() -> dict:
    try:
        guardado = json.loads(_arquivo().read_text())
        return guardado if isinstance(guardado, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar(guardado: dict) -> None:
    arquivo = _arquivo()
    try:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        provisorio = arquivo.with_suffix(f".{os.getpid()}.tmp")
        provisorio.write_text(json.dumps(guardado))
        provisorio.replace(arquivo)
    except OSError:
        pass  # sem gravar, consulta de novo na próxima vez


def da_aws(forcar: bool = False) -> dict:
    """Cada parte do que vem da AWS, do arquivo enquanto vale; consulta de novo
    a que venceu, ou todas se pediram (no máximo a cada INTERVALO_MINIMO)."""
    guardado, mudou, momento = _ler(), False, time.time()
    for chave, (validade, coletar) in PARTES.items():
        parte = guardado.get(chave)
        if isinstance(parte, dict) and "em" in parte and "dados" in parte:
            if "erro" in parte["dados"]:
                validade = VALIDADE_COM_ERRO
            if forcar:
                validade = min(validade, INTERVALO_MINIMO)
            if momento - parte["em"] < validade:
                continue
        try:
            dados = coletar()
        except Exception as e:  # noqa: BLE001 - cada bloco mostra o seu problema
            dados = {"erro": _explicar(e)}
        guardado[chave] = {"em": momento, "texto": agora().strftime("%d/%m/%Y %H:%M"), "dados": dados}
        mudou = True
    if mudou:
        _gravar(guardado)
    return {c: guardado[c]["dados"] | {"_em": guardado[c]["texto"]} for c in PARTES}


# ------------------------------------------------------------- Máquina


def _meminfo() -> dict[str, int]:
    valores = {}
    for linha in Path("/proc/meminfo").read_text().splitlines():
        nome, _, resto = linha.partition(":")
        valores[nome] = int(resto.split()[0]) * 1024
    return valores


def _situacao(servico: str) -> str:
    try:
        r = subprocess.run(["systemctl", "is-active", servico], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip()


def maquina() -> dict:
    """Uso da máquina agora (Linux; fora dele, só o que der para ler)."""
    disco = shutil.disk_usage("/")
    dados: dict = {
        "cpus": os.cpu_count() or 1,
        "disco": {"total": disco.total, "usado": disco.used},
        "carga": os.getloadavg() if hasattr(os, "getloadavg") else None,
        "memoria": None, "swap": None, "ligada": None, "servicos": {},
    }  # fmt: skip
    try:
        mem = _meminfo()
        dados["memoria"] = {"total": mem["MemTotal"], "usado": mem["MemTotal"] - mem["MemAvailable"]}
        if mem.get("SwapTotal"):
            dados["swap"] = {"total": mem["SwapTotal"], "usado": mem["SwapTotal"] - mem["SwapFree"]}
        dados["ligada"] = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, KeyError, ValueError):
        pass
    if shutil.which("systemctl"):
        dados["servicos"] = {s: _situacao(s) for s in SERVICOS}
    return dados


# ---------------------------------------------------------------- Banco


def banco(db: Session) -> dict:
    """Versão, conexões e o tamanho de cada banco no servidor MySQL."""
    if db.get_bind().dialect.name != "mysql":
        return {"erro": "Disponível só no MySQL (aqui o banco é SQLite)."}
    try:
        nomes = {i.banco: i.nome for i in db.scalars(sa.select(m.Imobiliaria))}
        central = db.get_bind().url.database
        tamanhos = db.execute(sa.text(
            "SELECT table_schema, COALESCE(SUM(data_length + index_length), 0), COUNT(*) "
            "FROM information_schema.tables GROUP BY table_schema"
        )).all()  # fmt: skip
        bancos = [
            {"banco": b, "bytes": int(t), "tabelas": int(n),
             "dono": "Cadastro da plataforma" if b == central else nomes.get(b, "")}
            for b, t, n in tamanhos if b not in _SISTEMA
        ]  # fmt: skip
        status = dict(db.execute(sa.text(
            "SHOW GLOBAL STATUS WHERE Variable_name IN ('Threads_connected', 'Uptime')"
        )).all())  # fmt: skip
        return {
            "versao": db.execute(sa.text("SELECT VERSION()")).scalar(),
            "host": db.get_bind().url.host,
            "conexoes": int(status.get("Threads_connected", 0)),
            "max_conexoes": db.execute(sa.text("SELECT @@max_connections")).scalar(),
            "ligado": float(status.get("Uptime", 0)),
            "bancos": sorted(bancos, key=lambda b: -b["bytes"]),
            "total": sum(b["bytes"] for b in bancos),
        }
    except Exception as e:  # noqa: BLE001 - mostra o problema no painel
        return {"erro": str(e)[:300]}


# ---------------------------------------------------------- Formatação


def tamanho(n: float | None) -> str:
    if n is None:
        return "—"
    for unidade in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unidade == "TB":
            break
        n /= 1024
    texto = f"{n:.0f}" if unidade == "B" or n >= 100 else f"{n:.1f}"
    return f"{texto.replace('.', ',')} {unidade}"


def dinheiro(valor: float | None, moeda: str = "USD") -> str:
    if valor is None:
        return "—"
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"US$ {texto}" if moeda == "USD" else f"{texto} {moeda}"


def duracao(segundos: float | None) -> str:
    if segundos is None:
        return "—"
    dias, resto = divmod(int(segundos), 86400)
    horas, resto = divmod(resto, 3600)
    if dias:
        return f"{dias} d {horas} h"
    return f"{horas} h {resto // 60} min"


def porcento(parte: float, todo: float) -> int:
    return round(100 * parte / todo) if todo else 0


def mes(iso: str) -> str:
    nomes = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
             "agosto", "setembro", "outubro", "novembro", "dezembro")  # fmt: skip
    d = date.fromisoformat(iso)
    return f"{nomes[d.month - 1]} de {d.year}"
