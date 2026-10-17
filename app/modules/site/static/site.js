// Interações do site: topo ao rolar, menu do celular, revelar ao rolar,
// contadores, fotos suaves, envio de formulário e visor de fotos.
(() => {
  const calmo = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Topo, barra de progresso e botão "voltar ao topo".
  const topo = document.querySelector(".topo");
  const progresso = document.querySelector(".progresso");
  const aoTopo = document.querySelector(".ao-topo");
  let agendado = false;
  const aoRolar = () => {
    agendado = false;
    const y = scrollY;
    topo?.classList.toggle("rolado", y > 24);
    aoTopo?.classList.toggle("visivel", y > 700);
    const total = document.documentElement.scrollHeight - innerHeight;
    progresso?.style.setProperty("--p", total > 0 ? (y / total).toFixed(4) : 0);
  };
  addEventListener("scroll", () => {
    if (!agendado) { agendado = true; requestAnimationFrame(aoRolar); }
  }, { passive: true });
  aoRolar();
  aoTopo?.addEventListener("click", () => scrollTo({ top: 0, behavior: calmo ? "auto" : "smooth" }));

  // Menu do celular.
  const botaoMenu = document.querySelector(".abrir-menu");
  const menu = document.querySelector(".menu");
  botaoMenu?.addEventListener("click", () => {
    const aberto = menu.classList.toggle("aberto");
    botaoMenu.setAttribute("aria-expanded", aberto);
  });
  menu?.querySelectorAll("a").forEach((a) => a.addEventListener("click", () => {
    menu.classList.remove("aberto");
    botaoMenu?.setAttribute("aria-expanded", "false");
  }));

  // Grupos com entrada em cascata: cada filho recebe o seu atraso.
  document.querySelectorAll("[data-cascata]").forEach((g) =>
    [...g.children].forEach((filho, i) => {
      filho.classList.add("revelar");
      filho.style.setProperty("--i", i % 6);
    }));

  // Revelar ao rolar.
  const revelar = document.querySelectorAll(".revelar");
  if (calmo || !("IntersectionObserver" in window)) {
    revelar.forEach((el) => el.classList.add("visivel"));
  } else {
    const obs = new IntersectionObserver((itens) => itens.forEach((e) => {
      if (!e.isIntersecting) return;
      const el = e.target;
      el.classList.add("visivel");
      obs.unobserve(el);
      // Depois de entrar, devolve o elemento às animações de hover normais.
      const atraso = 900 + (+getComputedStyle(el).getPropertyValue("--i") || 0) * 80;
      setTimeout(() => el.classList.remove("revelar", "visivel"), atraso);
    }), { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
    revelar.forEach((el) => obs.observe(el));
  }

  // Contadores animados (números reais vindos do servidor).
  const contar = (el) => {
    const alvo = +el.dataset.contar;
    if (calmo || !alvo) { el.textContent = alvo; return; }
    const inicio = performance.now();
    const passo = (t) => {
      const p = Math.min((t - inicio) / 1400, 1);
      el.textContent = Math.round(alvo * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(passo);
    };
    requestAnimationFrame(passo);
  };
  const contadores = document.querySelectorAll("[data-contar]");
  if ("IntersectionObserver" in window) {
    const obs = new IntersectionObserver((itens) => itens.forEach((e) => {
      if (e.isIntersecting) { contar(e.target); obs.unobserve(e.target); }
    }), { threshold: 0.6 });
    contadores.forEach((el) => obs.observe(el));
  } else contadores.forEach(contar);

  // Fotos aparecem suavemente quando terminam de carregar.
  document.querySelectorAll("img[data-suave]").forEach((img) => {
    const pronta = () => img.classList.add("carregada");
    if (img.complete) pronta();
    else { img.addEventListener("load", pronta); img.addEventListener("error", pronta); }
  });

  // Campo de envio de fotos/vídeos: mostra o que foi escolhido.
  document.querySelectorAll("input[data-envio]").forEach((input) => {
    const caixa = input.closest(".soltar");
    const nomes = caixa.querySelector(".escolhidos");
    input.addEventListener("change", () => {
      const n = input.files.length;
      nomes.textContent = n === 0 ? "" : n === 1 ? input.files[0].name : `${n} arquivos escolhidos`;
    });
    ["dragenter", "dragover"].forEach((ev) => input.addEventListener(ev, () => caixa.classList.add("sobre")));
    ["dragleave", "drop"].forEach((ev) => input.addEventListener(ev, () => caixa.classList.remove("sobre")));
  });

  // Copiar (ex.: PIX copia e cola).
  document.querySelectorAll("[data-copiar]").forEach((b) => b.addEventListener("click", async () => {
    const alvo = document.querySelector(b.dataset.copiar);
    try { await navigator.clipboard.writeText(alvo.value); } catch { alvo.select(); document.execCommand("copy"); }
    const texto = b.textContent;
    b.textContent = "Copiado!";
    setTimeout(() => { b.textContent = texto; }, 2000);
  }));

  // Formulários: botão mostra "enviando" (e volta ao usar o "voltar").
  document.querySelectorAll("form.formulario, form[data-enviando]").forEach((f) =>
    f.addEventListener("submit", () => f.querySelector("button[type=submit]")?.classList.add("enviando")));
  addEventListener("pageshow", () =>
    document.querySelectorAll(".enviando").forEach((b) => b.classList.remove("enviando")));

  // Visor de fotos (página do imóvel).
  const visor = document.querySelector(".visor");
  if (visor) {
    const fotos = JSON.parse(visor.dataset.fotos);
    const img = visor.querySelector("figure > img");
    const contador = visor.querySelector(".contador");
    const minis = visor.querySelector(".miniaturas");
    let atual = 0;
    fotos.forEach((u, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.dataset.i = i;
      b.setAttribute("aria-label", `Foto ${i + 1}`);
      const mini = document.createElement("img");
      mini.src = u;
      mini.alt = "";
      mini.loading = "lazy";
      b.append(mini);
      minis.append(b);
    });
    const mostrar = (n) => {
      atual = (n + fotos.length) % fotos.length;
      img.classList.add("trocando");
      setTimeout(() => {
        img.src = fotos[atual];
        img.classList.remove("trocando");
      }, calmo ? 0 : 180);
      contador.textContent = `${atual + 1} / ${fotos.length}`;
      minis.querySelectorAll("button").forEach((b, i) => b.classList.toggle("atual", i === atual));
      minis.children[atual]?.scrollIntoView({ block: "nearest", inline: "center" });
    };
    const abrir = (n) => {
      mostrar(n);
      visor.classList.add("aberto");
      document.body.style.overflow = "hidden";
      visor.querySelector(".fechar").focus();
    };
    const fechar = () => { visor.classList.remove("aberto"); document.body.style.overflow = ""; };
    document.querySelectorAll("[data-foto]").forEach((b) => b.addEventListener("click", () => abrir(+b.dataset.foto)));
    visor.querySelector(".fechar").onclick = fechar;
    visor.querySelector(".ant").onclick = () => mostrar(atual - 1);
    visor.querySelector(".prox").onclick = () => mostrar(atual + 1);
    minis.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (b) mostrar(+b.dataset.i);
    });
    visor.addEventListener("click", (e) => { if (e.target === visor) fechar(); });
    addEventListener("keydown", (e) => {
      if (!visor.classList.contains("aberto")) return;
      if (e.key === "Escape") fechar();
      if (e.key === "ArrowLeft") mostrar(atual - 1);
      if (e.key === "ArrowRight") mostrar(atual + 1);
    });
    // Arrastar para os lados no celular.
    let x0 = null;
    visor.addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; }, { passive: true });
    visor.addEventListener("touchend", (e) => {
      if (x0 === null) return;
      const dx = e.changedTouches[0].clientX - x0;
      if (Math.abs(dx) > 50) mostrar(atual + (dx < 0 ? 1 : -1));
      x0 = null;
    });
  }
})();
