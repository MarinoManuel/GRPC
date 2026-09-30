"use strict";
/* =========================================================================
   faísca: frontend do site de namoro gRPC

   JavaScript puro, sem framework e sem etapa de build: o navegador lê este
   arquivo direto. Tudo passa pelo Gateway:
     - REST (fetch) para login, feed, curtidas, perfil, conversas;
     - WebSocket para o chat (o Gateway faz a ponte com o stream
       bidirecional gRPC do Messaging);
     - /api/status a cada 3s, para o letreiro do sistema e para
       reagir ao vivo quando um serviço cai ou volta.
   ========================================================================= */

// Servido pelo próprio Gateway (http://localhost:8000): mesma origem.
// Aberto como arquivo local (file://): aponta para o Gateway padrão.
const API = location.protocol.startsWith("http") ? "" : "http://127.0.0.1:8000";
const WS_BASE = API
  ? "ws://127.0.0.1:8000"
  : `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}`;

const ABAS = ["descobrir", "curtidas", "chats", "perfil"];

const $ = (seletor, raiz = document) => raiz.querySelector(seletor);
const $$ = (seletor, raiz = document) => [...raiz.querySelectorAll(seletor)];
const enc = encodeURIComponent;

// localStorage pode estar bloqueado (aba anônima, etc.): nunca deixar quebrar.
const guardado = {
  ler(chave) { try { return localStorage.getItem(chave); } catch { return null; } },
  gravar(chave, valor) {
    try { valor == null ? localStorage.removeItem(chave) : localStorage.setItem(chave, valor); } catch { /* ignora */ }
  },
};

const estado = {
  eu: guardado.ler("faisca.user_id"),
  meuPerfil: null,
  aba: null,
  status: null,                 // último /api/status
  // O feed inteiro fica em memória e "indice" aponta o perfil da vez: assim
  // dá para voltar e avançar. "decisoes" lembra quem já foi curtido/passado.
  feed: [], indice: 0, decisoes: new Map(), feedCarregado: false, feedCarregando: false,
  conversas: [],
  conversaAtiva: null,          // { id, nome }
  ws: null, timerReconexao: null,
  idsMostrados: new Set(), ultimoDia: null,
  avatares: new Map(),          // user_id -> { foto, nome } (cache de fotos)
  degradado: { descobrir: false, curtidas: false, chats: false, perfil: false },
  timerConversas: null,
  nomePendente: false,          // nome novo aguardando chegar aos chats
  fotoCadastro: null,
};

/* =========================================================================
   Comunicação com o Gateway
   ========================================================================= */

class ErroApi extends Error {
  constructor(status, mensagem) { super(mensagem); this.status = status; }
}

/** Faz a requisição e trata erros; devolve a Response (status 0 = Gateway inacessível). */
async function requisitar(metodo, caminho, corpo) {
  const opcoes = { method: metodo, headers: { "Content-Type": "application/json" } };
  if (estado.eu) opcoes.headers["X-User-Id"] = estado.eu;
  if (corpo !== undefined) opcoes.body = JSON.stringify(corpo);

  let resposta;
  try {
    resposta = await fetch(API + caminho, opcoes);
  } catch {
    throw new ErroApi(0, "Sem conexão com o Gateway");
  }
  if (!resposta.ok) {
    const dados = await resposta.json().catch(() => ({}));
    // FastAPI devolve uma lista em "detail" quando faltam campos no JSON.
    const mensagem = Array.isArray(dados.detail) ? "Preencha todos os campos" : (dados.detail || "Algo deu errado");
    if (resposta.status === 401 && estado.eu && !caminho.startsWith("/api/login")) {
      sair();
      aviso("Sua sessão não vale mais: entre de novo.", "alerta");
    }
    throw new ErroApi(resposta.status, mensagem);
  }
  return resposta;
}

/** Chama a API REST do Gateway e devolve o JSON da resposta. */
async function api(metodo, caminho, corpo) {
  const resposta = await requisitar(metodo, caminho, corpo);
  return resposta.json().catch(() => ({}));
}

/**
 * Lê uma resposta NDJSON (um JSON por linha) AOS POUCOS: chama aoChegar(item)
 * para cada linha assim que ela chega pela rede, sem esperar o fim.
 * Devolve quantos itens chegaram.
 */
async function lerStream(caminho, aoChegar) {
  const resposta = await requisitar("GET", caminho);
  const leitor = resposta.body.getReader();
  const decodificador = new TextDecoder();
  let pendente = "";
  let total = 0;
  for (;;) {
    let parte;
    try {
      parte = await leitor.read();
    } catch {
      break; // a conexão caiu no meio: fica com o que já chegou
    }
    if (parte.done) break;
    pendente += decodificador.decode(parte.value, { stream: true });
    let fim;
    while ((fim = pendente.indexOf("\n")) >= 0) {
      const linha = pendente.slice(0, fim).trim();
      pendente = pendente.slice(fim + 1);
      if (linha) { aoChegar(JSON.parse(linha)); total++; }
    }
  }
  return total;
}

/* =========================================================================
   Pequenos utilitários de interface
   ========================================================================= */

function criar(tag, classe, texto) {
  const el = document.createElement(tag);
  if (classe) el.className = classe;
  if (texto != null) el.textContent = texto;
  return el;
}

const MATIZES = [12, 22, 34, 348, 330, 160, 192, 262, 45];
function matiz(id) {
  let h = 0;
  for (const c of String(id)) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return MATIZES[h % MATIZES.length];
}

/** Círculo com a inicial do nome: usado quando não há foto (ou o Discovery está fora). */
function monograma(nome, id) {
  const el = criar("span", "monograma", (nome || "?").trim().charAt(0).toUpperCase());
  el.style.setProperty("--matiz", matiz(id || nome));
  return el;
}

function imagem(src, alt = "") {
  const img = criar("img");
  img.src = src; img.alt = alt; img.draggable = false; img.decoding = "async";
  return img;
}

/**
 * Avatar de um usuário. Mostra a inicial na hora e, se a foto ainda não
 * estiver no cache, busca no Discovery (via Gateway). Se o Discovery estiver
 * fora, a inicial simplesmente fica: o chat continua perfeito sem a foto.
 */
function avatar(id, nome, classe = "avatar") {
  const el = criar("span", classe);
  el.dataset.avatar = id;
  preencherAvatar(el, id, nome);
  carregarAvatar(id);
  return el;
}

function preencherAvatar(el, id, nome) {
  const info = estado.avatares.get(id);
  el.replaceChildren(info?.foto ? imagem(info.foto, nome) : monograma(nome, id));
}

async function carregarAvatar(id) {
  const info = estado.avatares.get(id);
  if (info?.foto || info?.carregando) return;
  if (info?.falhouEm && Date.now() - info.falhouEm < 15000) return;
  estado.avatares.set(id, { carregando: true });
  try {
    const perfil = await api("GET", `/api/perfis/${enc(id)}`);
    estado.avatares.set(id, { foto: perfil.foto, nome: perfil.nome });
    $$(`[data-avatar="${CSS.escape(id)}"]`).forEach((el) => preencherAvatar(el, id, perfil.nome));
  } catch {
    estado.avatares.set(id, { falhouEm: Date.now() });
  }
}

/** Aviso flutuante (toast). tipo: "ok" | "alerta" | "falha". */
function aviso(texto, tipo = "ok") {
  const el = criar("div", "aviso");
  el.append(criar("i", `luz ${tipo}`), criar("span", null, texto));
  $("#avisos").append(el);
  setTimeout(() => { el.classList.add("saindo"); setTimeout(() => el.remove(), 300); }, 3800);
}

function hora(iso) {
  return new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function rotuloDia(data) {
  const hoje = new Date();
  const ontem = new Date(); ontem.setDate(hoje.getDate() - 1);
  if (data.toDateString() === hoje.toDateString()) return "hoje";
  if (data.toDateString() === ontem.toDateString()) return "ontem";
  return data.toLocaleDateString("pt-BR", { day: "numeric", month: "long" });
}

function tempoRelativo(iso) {
  if (!iso) return "";
  const segundos = (Date.now() - new Date(iso).getTime()) / 1000;
  if (segundos < 60) return "agora";
  if (segundos < 3600) return `${Math.floor(segundos / 60)} min`;
  if (segundos < 86400) return `${Math.floor(segundos / 3600)} h`;
  return new Date(iso).toLocaleDateString("pt-BR", { day: "numeric", month: "short" }).replace(".", "");
}

/** Faíscas saltando de um elemento (o botão de curtir). */
function soltarFaiscas(origem) {
  const r = origem.getBoundingClientRect();
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  for (let i = 0; i < 16; i++) {
    const f = criar("span", "faisca");
    const angulo = Math.random() * Math.PI * 2;
    const distancia = 55 + Math.random() * 85;
    const tamanho = 6 + Math.random() * 12;
    Object.assign(f.style, { left: `${cx - tamanho / 2}px`, top: `${cy - tamanho / 2}px`, width: `${tamanho}px`, height: `${tamanho}px` });
    f.style.setProperty("--dx", `${Math.cos(angulo) * distancia}px`);
    f.style.setProperty("--dy", `${Math.sin(angulo) * distancia}px`);
    if (i % 3 === 0) f.style.background = "var(--brasa-clara)";
    if (i % 5 === 0) f.style.background = "var(--papel)";
    document.body.append(f);
    setTimeout(() => f.remove(), 900);
  }
}

/* =========================================================================
   Letreiro do sistema: saúde dos serviços, ao vivo
   ========================================================================= */

// "LENTO" = o Health Check estourou o prazo: o serviço existe, a rede é que
// está lenta. Conta como no ar (não derruba abas nem dispara aviso de queda).
const noAr = (valor) => valor === "SERVING" || valor === "LENTO";
let statusEmAndamento = false;

async function atualizarStatus() {
  // Numa rede lenta o /api/status pode demorar mais que o intervalo de 3s:
  // não empilha uma consulta nova enquanto a anterior não voltar.
  if (statusEmAndamento) return;
  statusEmAndamento = true;
  let novo = null;
  try {
    const resposta = await fetch(API + "/api/status");
    novo = await resposta.json();
  } catch { /* Gateway fora: novo fica null */ }
  finally { statusEmAndamento = false; }

  const anterior = estado.status;
  estado.status = novo;
  desenharSistema(novo);

  if (estado.eu && anterior && novo) {
    for (const [servico, caiu, voltou] of [
      ["discovery", "Perfis indisponíveis no momento. Seus chats seguem funcionando.", "Perfis de volta ✦"],
      ["messaging", "Chat indisponível no momento. Descobrir segue funcionando.", "Chat de volta ✦"],
    ]) {
      if (noAr(anterior[servico]) && !noAr(novo[servico])) aviso(caiu, "falha");
      if (!noAr(anterior[servico]) && noAr(novo[servico])) aviso(voltou, "ok");
    }
  }

  // Aba em modo "degradado" e o serviço dela voltou? Recarrega sozinha.
  if (estado.eu && novo && estado.degradado[estado.aba]) {
    const servico = estado.aba === "chats" ? "messaging" : "discovery";
    if (noAr(novo[servico])) recarregarAba(estado.aba);
  }
  // Chat aberto e sem conexão, com o Messaging de volta? Reconecta já.
  if (estado.conversaAtiva && !estado.ws && novo && noAr(novo.messaging)) conectarChat();
  // Nome novo esperando chegar aos chats (fila de sincronização esvaziou)?
  if (estado.nomePendente && novo && novo.nomes_pendentes === 0) {
    estado.nomePendente = false;
    aviso("Seu nome novo já aparece nos chats ✦");
  }
}

function desenharSistema(s) {
  const linhas = s
    ? [["Discovery", s.discovery], ["Messaging", s.messaging]].map(([nome, valor]) => ({
        nome, ok: noAr(valor),
        luz: valor === "LENTO" ? "alerta" : noAr(valor) ? "ok" : "falha",
        texto: valor === "LENTO" ? "lento" : noAr(valor) ? "no ar" : "fora",
      }))
    : [{ nome: "Gateway", ok: false, luz: "falha", texto: "sem sinal" }];

  const painel = $("#sistema");
  painel.replaceChildren(criar("p", "sistema-titulo", "Sistema · ao vivo"));
  for (const l of linhas) {
    const linha = criar("div", `servico ${l.ok ? "" : "falha"}`);
    linha.title = `${l.nome}: ${l.texto}`;
    linha.append(criar("i", `luz ${l.luz}`), criar("b", null, l.nome), criar("small", null, l.texto));
    painel.append(linha);
  }
  if (s) {
    const fila = criar("div", "servico");
    fila.title = "Nomes aguardando sincronização com o Messaging";
    fila.append(criar("i", `luz ${s.nomes_pendentes ? "alerta" : "ok"}`), criar("b", null, "Fila de nomes"),
      criar("small", null, String(s.nomes_pendentes)));
    painel.append(fila);
  }
}

/* =========================================================================
   Degradação graciosa: a aba mostra uma tela explicativa no lugar do
   conteúdo quando o serviço dela está fora, e o resto do app segue normal.
   ========================================================================= */

const TEXTOS_DEGRADADO = {
  discovery: {
    rotulo: "Perfis · indisponível",
    titulo: "Os perfis saíram para <em>dar uma volta</em>.",
    texto: "Não conseguimos carregar perfis agora. <strong>Seus chats continuam funcionando normalmente</strong> enquanto isso.",
    irPara: ["chats", "Ir para os chats →"],
  },
  messaging: {
    rotulo: "Chat · indisponível",
    titulo: "As conversas deram <em>uma pausa</em>.",
    texto: "O chat está temporariamente fora do ar. <strong>Você pode continuar descobrindo pessoas</strong> e suas conversas voltam logo.",
    irPara: ["descobrir", "Ir para Descobrir →"],
  },
  gateway: {
    rotulo: "Sem conexão",
    titulo: "Estamos <em>sem sinal</em>.",
    texto: "Não conseguimos falar com o servidor agora. Assim que a conexão voltar, tudo reaparece aqui.",
    irPara: null,
  },
};

function degradar(aba, ligado, servico = "discovery") {
  const secao = $(`#aba-${aba}`);
  const conteudo = $("[data-conteudo]", secao);
  secao.querySelector(".degradado")?.remove();
  estado.degradado[aba] = ligado;
  conteudo.hidden = ligado;
  if (!ligado) return;

  const t = TEXTOS_DEGRADADO[servico];
  const bloco = $("#modelo-degradado").content.firstElementChild.cloneNode(true);
  $(".degradado-rotulo", bloco).textContent = t.rotulo;
  $(".degradado-titulo", bloco).innerHTML = t.titulo;
  $(".degradado-texto", bloco).innerHTML = t.texto;
  const acoes = $(".degradado-acoes", bloco);
  if (t.irPara) {
    const ir = criar("button", "botao-primario", null);
    ir.append(criar("span", null, t.irPara[1]));
    ir.addEventListener("click", () => irPara(t.irPara[0]));
    acoes.append(ir);
  }
  const tentar = criar("button", "botao-contorno", "Tentar agora");
  tentar.addEventListener("click", () => recarregarAba(aba));
  acoes.append(tentar);
  if (aba === "perfil") {
    const sairBtn = criar("button", "botao-texto", "Sair da conta");
    sairBtn.addEventListener("click", sair);
    acoes.append(sairBtn);
  }
  secao.append(bloco);
}

/** Decide, a partir do erro, se a aba entra em modo degradado ou só mostra um aviso. */
function tratarErroAba(aba, erro, servico) {
  if (erro.status === 503) degradar(aba, true, servico);
  else if (erro.status === 0) degradar(aba, true, "gateway");
  else if (erro.status !== 401) aviso(erro.message, "falha");
}

/**
 * Se o letreiro já sabe que o serviço da aba está fora, mostra a tela de
 * indisponível na hora, em vez de fazer um pedido que ficaria esperando
 * uma conexão que não vai responder. A volta é automática: quando o
 * letreiro vê o serviço no ar de novo, atualizarStatus() recarrega a aba.
 */
function jaSabemosQueEstaFora(aba, servico) {
  if (estado.status && !noAr(estado.status[servico])) {
    degradar(aba, true, servico);
    return true;
  }
  return false;
}

function recarregarAba(aba) {
  if (aba === "descobrir") carregarFeed();
  if (aba === "curtidas") carregarCurtidas();
  if (aba === "chats") carregarConversas();
  if (aba === "perfil") carregarMeuPerfil();
}

/* =========================================================================
   Entrada: login e cadastro
   ========================================================================= */

function mostrarEntrada() {
  $("#app").hidden = true;
  $("#tela-entrada").hidden = false;
  document.title = "faísca · entrar";
}

function trocarModoEntrada(modo) {
  $(".abas-entrada").dataset.modo = modo;
  $$(".abas-entrada button").forEach((b) => b.classList.toggle("ativa", b.dataset.modo === modo));
  $("#form-entrar").hidden = modo !== "entrar";
  $("#form-cadastrar").hidden = modo !== "cadastrar";
  $("#erro-entrada").textContent = "";
}

async function comBotaoOcupado(form, tarefa) {
  const botao = $("button[type=submit]", form);
  botao.disabled = true; botao.classList.add("carregando");
  $("#erro-entrada").textContent = "";
  try { await tarefa(); }
  catch (erro) { $("#erro-entrada").textContent = erro.message; }
  finally { botao.disabled = false; botao.classList.remove("carregando"); }
}

/** Reduz a foto no navegador (lado maior 1000px, JPEG) antes de enviar. */
function reduzirFoto(arquivo) {
  return new Promise((resolver, rejeitar) => {
    const img = new Image();
    const url = URL.createObjectURL(arquivo);
    img.onload = () => {
      const escala = Math.min(1, 1000 / Math.max(img.width, img.height));
      const tela = document.createElement("canvas");
      tela.width = Math.round(img.width * escala);
      tela.height = Math.round(img.height * escala);
      tela.getContext("2d").drawImage(img, 0, 0, tela.width, tela.height);
      URL.revokeObjectURL(url);
      resolver(tela.toDataURL("image/jpeg", 0.86));
    };
    img.onerror = () => { URL.revokeObjectURL(url); rejeitar(new Error("Não consegui ler essa imagem")); };
    img.src = url;
  });
}

async function escolherFoto(arquivo) {
  if (!arquivo || !arquivo.type.startsWith("image/")) return;
  try {
    estado.fotoCadastro = await reduzirFoto(arquivo);
    const img = $("#foto-drop img");
    img.src = estado.fotoCadastro; img.hidden = false;
    $(".foto-drop-texto").hidden = true;
  } catch (erro) {
    $("#erro-entrada").textContent = erro.message;
  }
}

function entrarComo(userId) {
  estado.eu = userId;
  guardado.gravar("faisca.user_id", userId);
  iniciarApp();
}

function sair() {
  fecharChat();
  clearInterval(estado.timerConversas);
  guardado.gravar("faisca.user_id", null);
  Object.assign(estado, {
    eu: null, meuPerfil: null, aba: null, feed: [], indice: 0, decisoes: new Map(), feedCarregado: false,
    conversas: [], conversaAtiva: null, nomePendente: false,
  });
  $("#pilha").replaceChildren();
  for (const aba of ABAS) degradar(aba, false);
  history.replaceState(null, "", location.pathname);
  mostrarEntrada();
}

/* =========================================================================
   Navegação entre abas
   ========================================================================= */

function iniciarApp() {
  $("#tela-entrada").hidden = true;
  $("#app").hidden = false;
  carregarMeuPerfil();
  carregarSeloCurtidas();
  irPara(location.hash.slice(1));
}

function irPara(aba) {
  if (!ABAS.includes(aba)) aba = "descobrir";
  if (location.hash !== `#${aba}`) history.replaceState(null, "", `#${aba}`);
  estado.aba = aba;
  document.title = `faísca · ${aba}`;
  $$(".aba").forEach((s) => { s.hidden = s.id !== `aba-${aba}`; });
  $$(".nav-item").forEach((b) => b.classList.toggle("ativo", b.dataset.aba === aba));

  clearInterval(estado.timerConversas);
  if (aba === "descobrir" && (!estado.feedCarregado || !estado.feed.length || estado.degradado.descobrir)) carregarFeed();
  if (aba === "curtidas") carregarCurtidas();
  if (aba === "chats") {
    carregarConversas();
    // Sem push de "conversa nova", a lista é atualizada a cada 6s.
    estado.timerConversas = setInterval(() => carregarConversas(true), 6000);
  }
  if (aba === "perfil") { desenharPerfil(); carregarMeuPerfil(); }
}

/* =========================================================================
   DESCOBRIR: pilha de cartões
   ========================================================================= */

/**
 * Busca o feed.
 *
 * Normal: só quem você ainda não curtiu nem passou.
 * procurarDeNovo (botão "Procurar de novo"): primeiro os perfis novos (ainda
 * não avaliados) e, logo em seguida, todos os que você já tinha visto, até o
 * fim. São dois pedidos em sequência; quem já veio no primeiro é pulado no
 * segundo, então ninguém aparece duas vezes.
 */
async function carregarFeed({ procurarDeNovo = false } = {}) {
  if (estado.feedCarregando || jaSabemosQueEstaFora("descobrir", "discovery")) return;
  estado.feedCarregando = true;
  const pilha = $("#pilha");
  if (!estado.feed.length || procurarDeNovo) pilha.replaceChildren(criar("div", "esqueleto"));

  // Cada perfil entra na pilha assim que chega (stream), sem esperar os
  // outros. O feed antigo só é trocado quando o primeiro perfil chega.
  let chegouAlgum = false;
  const recebidos = new Set();
  const receber = (perfil) => {
    if (recebidos.has(perfil.user_id)) return;
    recebidos.add(perfil.user_id);
    if (!chegouAlgum) {
      chegouAlgum = true;
      degradar("descobrir", false);
      // "decisoes" é mantido: quem você curtiu/passou continua marcado ao reaparecer.
      Object.assign(estado, { feed: [], indice: 0, feedCarregado: true });
      pilha.replaceChildren();
    }
    estado.avatares.set(perfil.user_id, { foto: perfil.foto, nome: perfil.nome });
    estado.feed.push(perfil);
    desenharPilha();
  };

  try {
    await lerStream("/api/feed", receber);
    const novos = recebidos.size;
    if (procurarDeNovo) {
      await lerStream("/api/feed?todos=true", receber);
      if (recebidos.size > novos) {
        aviso(novos
          ? `${novos} ${novos === 1 ? "pessoa nova" : "pessoas novas"} primeiro; depois, quem você já viu.`
          : "Ninguém novo por enquanto. Veja de novo quem já apareceu.", novos ? "ok" : "alerta");
      }
    }
    if (!recebidos.size) {
      degradar("descobrir", false);
      Object.assign(estado, { feed: [], indice: 0, feedCarregado: true });
    }
  } catch (erro) {
    if (!chegouAlgum) tratarErroAba("descobrir", erro, "discovery");
  } finally {
    estado.feedCarregando = false;
    // Redesenha no fim: troca o "carregando" pelo fim do feed, se for o caso.
    if (!estado.degradado.descobrir) desenharPilha();
  }
}

function criarCartao(perfil) {
  const cartao = criar("article", "cartao");
  cartao.dataset.id = perfil.user_id;
  cartao.append(perfil.foto ? imagem(perfil.foto, `Foto de ${perfil.nome}`) : monograma(perfil.nome, perfil.user_id));
  cartao.append(criar("span", "cartao-ficha"));
  const marca = criar("span", "cartao-marca");
  marca.hidden = true;
  cartao.append(marca);
  cartao.append(criar("span", "carimbo curtir", "Curti"), criar("span", "carimbo passar", "Passo"));
  const info = criar("div", "cartao-info");
  info.append(criar("h3", "cartao-nome", perfil.nome));
  if (perfil.bio) info.append(criar("p", "cartao-bio", perfil.bio));
  cartao.append(info);
  return cartao;
}

const doisDigitos = (n) => String(n).padStart(2, "0");

/**
 * Desenha os 3 cartões a partir de estado.indice (o do topo + 2 atrás).
 * Os cartões são reaproveitados pelo user_id, então quando o índice muda
 * eles só trocam de posição (data-pos) e o CSS anima a transição.
 * entrada: "baixo" (cartão novo surge por trás) ou "esquerda" (voltando).
 */
function desenharPilha(entrada = "baixo") {
  const pilha = $("#pilha");
  const visiveis = estado.feed.slice(estado.indice, estado.indice + 3);
  const ids = new Set(visiveis.map((p) => p.user_id));

  $$(".cartao:not(.saindo)", pilha).forEach((c) => { if (!ids.has(c.dataset.id)) c.remove(); });
  $(".fim-feed", pilha)?.remove();
  $(".esqueleto", pilha)?.remove();

  visiveis.forEach((perfil, i) => {
    let cartao = $(`.cartao[data-id="${CSS.escape(perfil.user_id)}"]:not(.saindo)`, pilha);
    if (!cartao) {
      cartao = criarCartao(perfil);
      const classe = i === 0 && entrada === "esquerda" ? "voltando" : "entrando";
      cartao.classList.add(classe);
      pilha.append(cartao);
      // dois frames: o navegador precisa "ver" o estado inicial para animar
      requestAnimationFrame(() => requestAnimationFrame(() => cartao.classList.remove(classe)));
    }
    cartao.dataset.pos = i;
    $(".cartao-ficha", cartao).textContent =
      `Nº ${doisDigitos(estado.indice + i + 1)} / ${doisDigitos(estado.feed.length)}`;

    const decisao = estado.decisoes.get(perfil.user_id);
    const marca = $(".cartao-marca", cartao);
    marca.hidden = !decisao;
    marca.className = `cartao-marca ${decisao || ""}`;
    marca.textContent = decisao === "curtir" ? "♥ Você curtiu" : "Você passou";
    if (i === 0) ativarArraste(cartao);
  });

  if (!visiveis.length && estado.feedCarregando) {
    // Você passou mais rápido do que os perfis chegam: mostra "carregando".
    pilha.append(criar("div", "esqueleto"));
  } else if (!visiveis.length) {
    const fim = criar("div", "fim-feed");
    fim.innerHTML = "<h3>Você viu <em>todo mundo</em> por agora.</h3><p>Volte com a seta para rever alguém, ou procure de novo.</p>";
    const botao = criar("button", "botao-contorno", "Procurar de novo");
    botao.addEventListener("click", () => carregarFeed({ procurarDeNovo: true }));
    fim.append(botao);
    pilha.append(fim);
  }

  ["#botao-passar", "#botao-curtir", "#botao-mensagem", "#botao-proxima"].forEach((s) => { $(s).disabled = !visiveis.length; });
  $("#botao-anterior").disabled = estado.indice === 0;

  const restantes = estado.feed.length - estado.indice;
  $("#contador-feed").innerHTML = restantes > 0
    ? `<strong>${restantes}</strong> ${restantes === 1 ? "pessoa esperando" : "pessoas esperando"} por você`
    : estado.feedCarregando ? "Procurando pessoas…" : "Ninguém novo por enquanto";

  const proximos = estado.feed.slice(estado.indice + 1, estado.indice + 7);
  const lado = $("#a-seguir");
  lado.replaceChildren();
  if (proximos.length) {
    lado.append(criar("h4", null, "A seguir"));
    const lista = criar("ol");
    proximos.forEach((p, i) => { const li = criar("li", null, p.nome); li.style.animationDelay = `${i * 50}ms`; lista.append(li); });
    lado.append(lista);
  }
}

/** Arrastar o cartão do topo: direita curte, esquerda passa. */
function ativarArraste(cartao) {
  if (cartao.dataset.arraste) return;
  cartao.dataset.arraste = "1";
  const carimboCurtir = $(".carimbo.curtir", cartao);
  const carimboPassar = $(".carimbo.passar", cartao);
  let x0 = 0, y0 = 0, dx = 0, dy = 0, arrastando = false;

  cartao.addEventListener("pointerdown", (e) => {
    if (cartao.dataset.pos !== "0" || cartao.classList.contains("saindo")) return;
    arrastando = true; x0 = e.clientX; y0 = e.clientY; dx = dy = 0;
    cartao.setPointerCapture(e.pointerId);
    cartao.style.transition = "none";
  });
  cartao.addEventListener("pointermove", (e) => {
    if (!arrastando) return;
    dx = e.clientX - x0; dy = e.clientY - y0;
    cartao.style.transform = `translate(${dx}px, ${dy * 0.35}px) rotate(${dx / 16}deg)`;
    carimboCurtir.style.opacity = Math.max(0, Math.min(1, dx / 90));
    carimboPassar.style.opacity = Math.max(0, Math.min(1, -dx / 90));
  });
  const soltar = () => {
    if (!arrastando) return;
    arrastando = false;
    cartao.style.transition = "";
    if (dx > 110) decidir("curtir");
    else if (dx < -110) decidir("passar");
    else {
      cartao.style.transform = "";
      carimboCurtir.style.opacity = carimboPassar.style.opacity = "";
    }
  };
  cartao.addEventListener("pointerup", soltar);
  cartao.addEventListener("pointercancel", soltar);
}

/** Tira o cartão do topo com uma animação. tipo: "curtir" | "passar" | "pular". */
function animarSaida(perfil, tipo) {
  const cartao = $(`.cartao[data-id="${CSS.escape(perfil.user_id)}"]:not(.saindo)`, $("#pilha"));
  if (!cartao) return;
  const direcao = tipo === "curtir" ? 1 : -1;
  cartao.classList.add("saindo");
  if (tipo !== "pular") $(`.carimbo.${tipo}`, cartao).style.opacity = 1;
  cartao.style.transition = "transform .6s var(--curva), opacity .6s";
  cartao.style.transform = tipo === "pular"
    ? "translate(-120vw, -10px) rotate(-14deg)"
    : `translate(${direcao * 120}vw, 60px) rotate(${direcao * 30}deg)`;
  cartao.style.opacity = "0";
  setTimeout(() => cartao.remove(), 650);
}

/** Volta para o perfil anterior (ele reaparece vindo da esquerda). */
function perfilAnterior() {
  if (estado.indice === 0) return;
  estado.indice--;
  desenharPilha("esquerda");
}

/** Avança para o próximo perfil sem curtir nem passar. */
function proximoPerfil() {
  const perfil = estado.feed[estado.indice];
  if (!perfil) return;
  animarSaida(perfil, "pular");
  estado.indice++;
  desenharPilha();
}

async function decidir(acao) {
  const perfil = estado.feed[estado.indice];
  if (!perfil) return;
  const decisaoAnterior = estado.decisoes.get(perfil.user_id);

  if (acao === "curtir") soltarFaiscas($("#botao-curtir"));
  animarSaida(perfil, acao);
  estado.decisoes.set(perfil.user_id, acao);
  estado.indice++;
  desenharPilha();

  try {
    await api("POST", `/api/perfis/${enc(perfil.user_id)}/${acao}`);
    if (acao === "curtir") aviso(`${perfil.nome} vai ver a sua curtida ✦`);
  } catch (erro) {
    if (decisaoAnterior) estado.decisoes.set(perfil.user_id, decisaoAnterior);
    else estado.decisoes.delete(perfil.user_id);
    aviso(erro.status === 503 || erro.status === 0
      ? "Não foi possível registrar agora. Tente de novo em instantes."
      : erro.message, "falha");
  }
}

/* =========================================================================
   CURTIDAS: mural de polaroides
   ========================================================================= */

function criarPolaroid(perfil, i) {
  const figura = criar("figure", "polaroid");
  figura.style.animationDelay = `${i * 70}ms`;
  const foto = criar("div", "polaroid-foto");
  foto.append(perfil.foto ? imagem(perfil.foto, `Foto de ${perfil.nome}`) : monograma(perfil.nome, perfil.user_id));
  const legenda = criar("figcaption");
  legenda.append(criar("span", null, perfil.nome));
  const botao = criar("button");
  botao.title = `Mandar mensagem para ${perfil.nome}`;
  botao.setAttribute("aria-label", botao.title);
  botao.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 3.5V17A2.5 2.5 0 0 1 4 14.5z"/></svg>';
  botao.addEventListener("click", () => abrirChatCom(perfil.user_id, perfil.nome));
  legenda.append(botao);
  figura.append(foto, legenda);
  return figura;
}

async function carregarCurtidas() {
  if (jaSabemosQueEstaFora("curtidas", "discovery")) return;
  const mural = $("#mural");
  try {
    const perfis = await api("GET", "/api/quem-me-curtiu");
    degradar("curtidas", false);
    perfis.forEach((p) => estado.avatares.set(p.user_id, { foto: p.foto, nome: p.nome }));
    mural.replaceChildren(...perfis.map(criarPolaroid));
    if (!perfis.length) {
      mural.innerHTML = '<div class="vazio"><h3>Ainda <em>ninguém</em> por aqui.</h3><p>Quando alguém curtir você, a foto aparece presa neste mural.</p></div>';
    }
    definirSeloCurtidas(perfis.length);
  } catch (erro) {
    tratarErroAba("curtidas", erro, "discovery");
  }
}

async function carregarSeloCurtidas() {
  try { definirSeloCurtidas((await api("GET", "/api/quem-me-curtiu")).length); } catch { /* sem selo */ }
}

function definirSeloCurtidas(total) {
  const item = $('.nav-item[data-aba="curtidas"]');
  $(".selo", item)?.remove();
  if (total) item.append(criar("span", "selo", String(total)));
}

/* =========================================================================
   CHATS: lista + conversa ao vivo (WebSocket → gRPC bidirecional)
   ========================================================================= */

async function carregarConversas(silencioso = false) {
  if (jaSabemosQueEstaFora("chats", "messaging")) return;
  try {
    estado.conversas = await api("GET", "/api/conversas");
    degradar("chats", false);
    desenharConversas();
  } catch (erro) {
    if (!silencioso || erro.status === 503 || erro.status === 0) tratarErroAba("chats", erro, "messaging");
  }
}

function desenharConversas() {
  const lista = [...estado.conversas];
  const ativa = estado.conversaAtiva;
  if (ativa && !lista.some((c) => c.outro_user_id === ativa.id)) {
    lista.unshift({ outro_user_id: ativa.id, outro_nome: ativa.nome, ultima_mensagem: "Conversa nova", ultima_em: null });
  }
  const caixa = $("#conversas");
  if (!lista.length) {
    caixa.innerHTML = '<div class="vazio"><h3>Nenhuma <em>conversa</em>.</h3><p>Em Descobrir, toque no balão de qualquer perfil para puxar assunto.</p></div>';
    return;
  }
  caixa.replaceChildren(...lista.map((c) => {
    const item = criar("button", `item-conversa ${ativa?.id === c.outro_user_id ? "ativa" : ""}`);
    const tempo = criar("time", null, tempoRelativo(c.ultima_em));
    if (c.ultima_em) tempo.dateTime = c.ultima_em;
    item.append(avatar(c.outro_user_id, c.outro_nome), criar("strong", null, c.outro_nome), tempo,
      criar("p", null, c.ultima_mensagem));
    item.addEventListener("click", () => abrirConversa(c.outro_user_id, c.outro_nome));
    return item;
  }));
}

/** Abre o chat com alguém: vem do botão de mensagem no feed ou nas curtidas. */
function abrirChatCom(id, nome) {
  estado.conversaAtiva = null;
  irPara("chats");
  abrirConversa(id, nome);
}

function abrirConversa(id, nome) {
  $(".chats").classList.add("abriu");
  if (estado.conversaAtiva?.id === id && estado.ws) return;

  estado.conversaAtiva = { id, nome };
  $("#conversa-vazia").hidden = true;
  $("#conversa-ativa").hidden = false;
  $("#conversa-nome").textContent = nome;
  $("#conversa-avatar").replaceChildren(avatar(id, nome, "avatar conversa-avatar"));
  $("#mensagens").replaceChildren();
  estado.idsMostrados = new Set();
  estado.ultimoDia = null;
  desenharConversas();
  conectarChat();
  if (matchMedia("(pointer: fine)").matches) $("#campo-mensagem").focus();
}

function fecharChat() {
  clearTimeout(estado.timerReconexao);
  if (estado.ws) { estado.ws.onclose = null; estado.ws.close(); estado.ws = null; }
}

function conectarChat() {
  const alvo = estado.conversaAtiva;
  if (!alvo || !estado.eu) return;
  fecharChat();

  const ws = new WebSocket(`${WS_BASE}/ws/chat/${enc(alvo.id)}?user_id=${enc(estado.eu)}`);
  estado.ws = ws;
  ws.onmessage = (evento) => {
    const mensagem = JSON.parse(evento.data);
    if (mensagem.erro) return; // o Gateway avisou que o chat caiu; o onclose reconecta
    adicionarMensagem(mensagem);
  };
  ws.onclose = () => {
    if (estado.ws !== ws) return;
    estado.ws = null;
    // Reconexão feita pela APLICAÇÃO (sem aparecer na tela): o histórico volta inteiro e as
    // mensagens repetidas são ignoradas pelo id.
    estado.timerReconexao = setTimeout(() => {
      if (estado.conversaAtiva?.id === alvo.id && !estado.ws) conectarChat();
    }, 3000);
  };
}

function adicionarMensagem(m) {
  if (estado.idsMostrados.has(m.id)) return;
  estado.idsMostrados.add(m.id);
  const caixa = $("#mensagens");
  const pertoDoFim = caixa.scrollHeight - caixa.scrollTop - caixa.clientHeight < 120;
  const minha = m.de_user_id === estado.eu;
  const data = new Date(m.enviada_em);

  if (data.toDateString() !== estado.ultimoDia) {
    estado.ultimoDia = data.toDateString();
    caixa.append(criar("div", "separador-dia", rotuloDia(data)));
  }
  const balao = criar("div", `balao ${minha ? "meu" : ""}`, m.texto);
  balao.append(criar("time", null, hora(m.enviada_em)));
  caixa.append(balao);
  if (minha || pertoDoFim) caixa.scrollTop = caixa.scrollHeight;

  // O nome vem do cache do Messaging: se a pessoa trocou de nome e a fila
  // de sincronização já entregou, o cabeçalho se atualiza aqui.
  if (!minha && estado.conversaAtiva && m.de_nome && m.de_nome !== estado.conversaAtiva.nome) {
    estado.conversaAtiva.nome = m.de_nome;
    $("#conversa-nome").textContent = m.de_nome;
  }

  // Atualiza a prévia na lista de conversas sem esperar o próximo ciclo.
  const conversa = estado.conversas.find((c) => c.outro_user_id === estado.conversaAtiva?.id);
  if (conversa) {
    conversa.ultima_mensagem = m.texto;
    conversa.ultima_em = m.enviada_em;
    estado.conversas.sort((a, b) => (b.ultima_em || "").localeCompare(a.ultima_em || ""));
    desenharConversas();
  } else if (estado.aba === "chats") {
    carregarConversas(true);
  }
}

function enviarMensagem() {
  const campo = $("#campo-mensagem");
  const texto = campo.value.trim();
  if (!texto) return;
  if (!estado.ws || estado.ws.readyState !== WebSocket.OPEN) {
    aviso("Sem conexão com o chat agora. Tentando reconectar…", "alerta");
    return;
  }
  // A mensagem só aparece quando o Messaging devolve a confirmação pelo
  // stream (com id e horário do servidor): o que você vê foi mesmo salvo.
  estado.ws.send(JSON.stringify({ texto }));
  campo.value = "";
  campo.style.height = "";
}

/* =========================================================================
   PERFIL
   ========================================================================= */

async function carregarMeuPerfil() {
  try {
    const perfil = await api("GET", "/api/meu-perfil");
    estado.meuPerfil = perfil;
    estado.avatares.set(estado.eu, { foto: perfil.foto, nome: perfil.nome });
    degradar("perfil", false);
    desenharPerfil();
  } catch (erro) {
    if (estado.aba === "perfil") tratarErroAba("perfil", erro, "discovery");
  }
  desenharNavAvatar();
}

function desenharNavAvatar() {
  const p = estado.meuPerfil;
  $("#nav-avatar").replaceChildren(p?.foto ? imagem(p.foto) : monograma(p?.nome || "·", estado.eu));
}

function desenharPerfil() {
  const p = estado.meuPerfil;
  if (!p) return;
  $("#perfil-foto").replaceChildren(p.foto ? imagem(p.foto, "Sua foto") : monograma(p.nome, estado.eu));
  const legenda = $("#perfil-legenda");
  legenda.replaceChildren(document.createTextNode(p.nome), criar("small", null, p.bio || "Sem bio ainda"));
  const form = $("#form-perfil");
  if (!form.contains(document.activeElement)) {
    form.nome.value = p.nome;
    form.bio.value = p.bio || "";
    atualizarContadores();
  }
}

async function salvarPerfil(evento) {
  evento.preventDefault();
  const form = evento.target;
  const p = estado.meuPerfil || { nome: "", bio: "" };
  const corpo = {};
  const nome = form.nome.value.trim();
  const bio = form.bio.value.trim();
  if (nome !== p.nome) corpo.nome = nome;
  if (bio !== (p.bio || "")) corpo.bio = bio;
  if (!Object.keys(corpo).length) { aviso("Nada mudou por aqui.", "alerta"); return; }

  const botao = $("button[type=submit]", form);
  botao.disabled = true;
  try {
    const resposta = await api("PATCH", "/api/meu-perfil", corpo);
    estado.meuPerfil = { ...p, ...corpo };
    estado.avatares.set(estado.eu, { foto: p.foto, nome: estado.meuPerfil.nome });
    desenharPerfil();
    desenharNavAvatar();
    // Se a cópia do nome usada nos chats ficou pendente (fila de retry do
    // Gateway), avisamos quando ela for entregue (ver atualizarStatus).
    if (resposta.nome_nos_chats === "pendente") {
      estado.nomePendente = true;
      aviso("Perfil salvo. Seu nome novo aparece nos chats em instantes.");
    } else {
      aviso("Perfil atualizado ✦");
    }
  } catch (erro) {
    aviso(erro.status === 503 || erro.status === 0
      ? "Não foi possível salvar agora. Tente de novo em instantes."
      : erro.message, "falha");
  } finally {
    botao.disabled = false;
  }
}

function atualizarContadores() {
  $$(".contador").forEach((contador) => {
    const campo = contador.closest(".campo").querySelector("textarea, input");
    contador.textContent = `${campo.value.length}/${campo.maxLength}`;
  });
}

/* =========================================================================
   Ligações de eventos e início
   ========================================================================= */

function ligarEventos() {
  // Entrada
  $$(".abas-entrada button").forEach((b) => b.addEventListener("click", () => trocarModoEntrada(b.dataset.modo)));

  $("#form-entrar").addEventListener("submit", (e) => {
    e.preventDefault();
    const form = e.target;
    comBotaoOcupado(form, async () => {
      const r = await api("POST", "/api/login", { email: form.email.value, senha: form.senha.value });
      entrarComo(r.user_id);
    });
  });

  const drop = $("#foto-drop");
  $("input[type=file]", drop).addEventListener("change", (e) => escolherFoto(e.target.files[0]));
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("input", drop).click(); } });
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("arrastando"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("arrastando"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("arrastando"); escolherFoto(e.dataTransfer.files[0]); });

  $("#form-cadastrar").addEventListener("submit", (e) => {
    e.preventDefault();
    const form = e.target;
    comBotaoOcupado(form, async () => {
      if (!estado.fotoCadastro) throw new Error("Escolha uma foto: ela é a primeira coisa que as pessoas veem.");
      const r = await api("POST", "/api/cadastro", {
        email: form.email.value, senha: form.senha.value, nome: form.nome.value, bio: form.bio.value,
        foto_base64: estado.fotoCadastro, extensao_foto: "jpg",
      });
      entrarComo(r.user_id);
      aviso(`Bem-vindo(a), ${form.nome.value.trim()} ✦`);
    });
  });

  $$("textarea[maxlength], input[maxlength]").forEach((c) => c.addEventListener("input", atualizarContadores));

  // Navegação
  $$(".nav-item").forEach((b) => b.addEventListener("click", () => irPara(b.dataset.aba)));
  window.addEventListener("hashchange", () => { if (estado.eu) irPara(location.hash.slice(1)); });

  // Descobrir
  $("#botao-curtir").addEventListener("click", () => decidir("curtir"));
  $("#botao-passar").addEventListener("click", () => decidir("passar"));
  const conversarComAtual = () => {
    const p = estado.feed[estado.indice];
    if (p) abrirChatCom(p.user_id, p.nome);
  };
  $("#botao-mensagem").addEventListener("click", conversarComAtual);
  $("#botao-anterior").addEventListener("click", perfilAnterior);
  $("#botao-proxima").addEventListener("click", proximoPerfil);
  document.addEventListener("keydown", (e) => {
    if (estado.aba !== "descobrir" || $("#app").hidden || e.target.closest("input, textarea")) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const tecla = e.key.toLowerCase();
    if (tecla === "arrowleft") perfilAnterior();
    else if (tecla === "arrowright") proximoPerfil();
    else if (tecla === "c") decidir("curtir");
    else if (tecla === "x") decidir("passar");
    else if (tecla === "m") conversarComAtual();
  });

  // Chats
  $("#compositor").addEventListener("submit", (e) => { e.preventDefault(); enviarMensagem(); });
  const campo = $("#campo-mensagem");
  campo.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviarMensagem(); } });
  campo.addEventListener("input", () => { campo.style.height = "auto"; campo.style.height = `${campo.scrollHeight}px`; });
  $("#voltar-conversas").addEventListener("click", () => $(".chats").classList.remove("abriu"));

  // Perfil
  $("#form-perfil").addEventListener("submit", salvarPerfil);
  $("#botao-sair").addEventListener("click", sair);
}

function iniciar() {
  ligarEventos();
  atualizarStatus();
  setInterval(atualizarStatus, 3000);
  if (estado.eu) iniciarApp();
  else mostrarEntrada();
}

iniciar();
