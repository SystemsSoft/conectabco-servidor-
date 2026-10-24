"""Painel da plataforma > Infraestrutura: gasto da AWS (guardado em arquivo),
instância e banco do Lightsail, servidor, bucket e bancos MySQL — tudo só
leitura, sem tocar na AWS de verdade."""

from datetime import datetime, timezone

import pytest
from botocore.exceptions import ClientError

from app.central import infraestrutura as infra
from app.central import services as central
from app.core.config import get_settings
from app.core.errors import RegraNegocio
from tests.central.test_painel import _csrf, _entrar, painel  # noqa: F401 - fixture


class Falso:
    """Cliente boto3 falso: conta as consultas ao Cost Explorer."""

    consultas = 0
    erro: Exception | None = None
    lightsail: list[str] = []

    def __init__(self, servico: str, regiao: str):
        self.servico = servico

    def get_cost_and_usage(self, **kw):
        Falso.consultas += 1
        if Falso.erro:
            raise Falso.erro
        inicio = kw["TimePeriod"]["Start"]

        def grupo(nome, valor):
            return {"Keys": [nome], "Metrics": {"UnblendedCost": {"Amount": str(valor), "Unit": "USD"}}}

        return {"ResultsByTime": [
            {"TimePeriod": {"Start": inicio}, "Groups": [grupo("Amazon Lightsail", 15)]},
            {"TimePeriod": {"Start": datetime.now(timezone.utc).date().replace(day=1).isoformat()},
             "Groups": [grupo("Amazon Elastic Compute Cloud - Compute", 7.5),
                        grupo("Amazon Lightsail", 10.25), grupo("AWS Key Management Service", 0.001)]},
        ]}  # fmt: skip

    def get_cost_forecast(self, **kw):
        return {"Total": {"Amount": "12.25", "Unit": "USD"}}

    def get_bucket_location(self, Bucket):
        return {"LocationConstraint": "sa-east-1"}

    # Lightsail: só responde pelos nomes configurados.
    def get_instance(self, instanceName):
        Falso.lightsail.append(instanceName)
        assert instanceName == "AssociacaoServer"
        return {"instance": {
            "name": instanceName, "state": {"name": "running"}, "publicIpAddress": "44.223.83.147",
            "isStaticIp": True, "location": {"availabilityZone": "us-east-1a"},
            "blueprintName": "Amazon Linux 2023", "bundleId": "small_3_0",
            "hardware": {"cpuCount": 2, "ramSizeInGb": 2.0, "disks": [{"sizeInGb": 60}]},
        }}  # fmt: skip

    def get_relational_database(self, relationalDatabaseName):
        Falso.lightsail.append(relationalDatabaseName)
        if relationalDatabaseName != "AssociacaoDatabase":
            raise ClientError({"Error": {"Code": "NotFoundException"}}, "GetRelationalDatabase")
        return {"relationalDatabase": {
            "name": relationalDatabaseName, "state": "available", "engine": "mysql",
            "engineVersion": "8.4.5", "location": {"availabilityZone": "us-east-1a"},
            "relationalDatabaseBundleId": "micro_2_0", "backupRetentionEnabled": True,
            "latestRestorableTime": datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc),
            "publiclyAccessible": True, "masterEndpoint": {"address": "ls-abc.us-east-1.rds.amazonaws.com"},
            "hardware": {"cpuCount": 2, "ramSizeInGb": 1.0, "diskSizeInGb": 40},
        }}  # fmt: skip

    def get_bundles(self, **kw):
        return {"bundles": [{"bundleId": "nano_3_0", "price": 5.0}, {"bundleId": "small_3_0", "price": 12.0}]}

    def get_relational_database_bundles(self, **kw):
        return {"bundles": [{"bundleId": "micro_2_0", "price": 15.0}]}

    def _pontos(self, metricName, statistics, **kw):
        valores = {"CPUUtilization": 37.4, "BurstCapacityPercentage": 81, "StatusCheckFailed": 0,
                   "DatabaseConnections": 6, "FreeStorageSpace": 30 * 1024**3,
                   "FreeableMemory": 256 * 1024**2}  # fmt: skip
        ponto = {"timestamp": datetime.now(timezone.utc), statistics[0].lower(): valores[metricName]}
        return {"metricData": [ponto]}

    get_instance_metric_data = get_relational_database_metric_data = _pontos

    def get_metric_statistics(self, MetricName, **kw):
        valor = 3 * 1024**3 if MetricName == "BucketSizeBytes" else 1234
        return {"Datapoints": [{"Timestamp": datetime.now(timezone.utc), "Average": valor}]}


@pytest.fixture
def aws(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "infra_cache", str(tmp_path / "infra.json"))
    monkeypatch.setattr(infra, "_cliente", Falso)
    Falso.consultas, Falso.erro, Falso.lightsail = 0, None, []
    return Falso


def test_pagina_mostra_gasto_servidor_bucket_e_banco(painel, aws):  # noqa: F811
    assert painel.get("/plataforma/infraestrutura").headers["location"] == "/plataforma/entrar"
    _entrar(painel)
    r = painel.get("/plataforma/infraestrutura")
    assert r.status_code == 200 and r.headers["X-Frame-Options"] == "DENY"
    pagina = r.text
    assert "US$ 17,75" in pagina  # até agora (o centavo do KMS some da lista)
    assert "US$ 30,00" in pagina and "US$ 15,00" in pagina  # previsão e mês passado
    assert "Amazon Lightsail" in pagina and "Key Management" not in pagina
    assert "3,0 GB" in pagina and "1.234" in pagina and "sa-east-1" in pagina
    assert "AssociacaoServer" in pagina and "44.223.83.147" in pagina and "Ligada" in pagina
    assert "small_3_0" in pagina and "US$ 12,00/mês" in pagina and "37%" in pagina and "81%" in pagina
    assert "AssociacaoDatabase" in pagina and "US$ 15,00/mês" in pagina and "mysql 8.4.5" in pagina
    assert "10,0 GB de 40,0 GB (25%)" in pagina and "até 24/10 15:00" in pagina
    assert "Disco" in pagina
    assert "Disponível só no MySQL" in pagina


def test_aws_fica_guardada_e_atualizar_tem_intervalo_minimo(painel, aws, monkeypatch):  # noqa: F811
    csrf = _entrar(painel)
    painel.get("/plataforma/infraestrutura")
    painel.get("/plataforma/infraestrutura")
    assert aws.consultas == 1  # a segunda veio do arquivo

    assert painel.post("/plataforma/infraestrutura").status_code == 403
    r = painel.post("/plataforma/infraestrutura", data={"csrf": csrf})
    assert r.headers["location"] == "/plataforma/infraestrutura?msg=aws"
    assert aws.consultas == 1  # pediu cedo demais: continua o guardado

    agora = infra.time.time()
    monkeypatch.setattr(infra.time, "time", lambda: agora + infra.INTERVALO_MINIMO + 1)
    painel.post("/plataforma/infraestrutura", data={"csrf": csrf})
    assert aws.consultas == 2
    painel.get("/plataforma/infraestrutura")
    assert aws.consultas == 2  # ainda dentro das 12 h


def test_lightsail_atualiza_em_minutos_e_o_custo_continua_guardado(painel, aws, monkeypatch):  # noqa: F811
    _entrar(painel)
    painel.get("/plataforma/infraestrutura")
    assert aws.lightsail == ["AssociacaoServer", "AssociacaoDatabase"] and aws.consultas == 1
    agora = infra.time.time()
    monkeypatch.setattr(infra.time, "time", lambda: agora + infra.VALIDADE_LIGHTSAIL + 1)
    painel.get("/plataforma/infraestrutura")
    assert len(aws.lightsail) == 4 and aws.consultas == 1


def test_nome_errado_no_lightsail_aparece_no_bloco(painel, aws, monkeypatch):  # noqa: F811
    monkeypatch.setattr(get_settings(), "lightsail_banco", "OutroBanco")
    _entrar(painel)
    pagina = painel.get("/plataforma/infraestrutura").text
    assert "Lightsail: Não encontrado no Lightsail (us-east-1): confira o nome" in pagina
    assert "AssociacaoServer" in pagina  # a instância continua aparecendo


def test_sem_credenciais_explica_e_tenta_de_novo_logo(painel, aws, monkeypatch):  # noqa: F811
    from botocore.exceptions import NoCredentialsError

    aws.erro = NoCredentialsError()
    _entrar(painel)
    assert "AWS_ACCESS_KEY_ID" in painel.get("/plataforma/infraestrutura").text
    agora = infra.time.time()
    monkeypatch.setattr(infra.time, "time", lambda: agora + infra.VALIDADE_COM_ERRO + 1)
    aws.erro = None
    assert "US$ 17,75" in painel.get("/plataforma/infraestrutura").text
    assert aws.consultas == 2


def test_infraestrutura_nao_pode_ser_identificador_de_imobiliaria(plataforma):
    with central.sessao() as db, pytest.raises(RegraNegocio, match="reservado"):
        central.validar_nova(db, "infraestrutura", "Infra Imóveis")


def test_formatacao():
    assert infra.tamanho(512) == "512 B"
    assert infra.tamanho(1536) == "1,5 KB"
    assert infra.tamanho(250 * 1024**2) == "250 MB"
    assert infra.dinheiro(1234.5) == "US$ 1.234,50"
    assert infra.duracao(90061) == "1 d 1 h"
    assert infra.duracao(3720) == "1 h 2 min"
    assert infra.mes("2026-10-01") == "outubro de 2026"
