"""R1 (sem internet), R2 (verificação do ML), R3 (Linkbuilder interrompido), R4 (erros da
Shopee), anti-repetição, rodízio espalhado e cupons (lista do painel + campanhas da Shopee)."""
import datetime as dt
import logging
from contextlib import contextmanager

import pytest

from ofertas import afiliado_ml, cupons, db, pipeline
from ofertas import config as cfg
from ofertas.config import config
from ofertas.models import ConfigCupons, Cupom, Grupo, Oferta
from ofertas.sources import ml_pagina, shopee
from ofertas.sources.shopee import ErroShopee


class Destino:
    nome = "console"

    def __init__(self):
        self.envios = []

    def enviar(self, o, msg, grupo):
        self.envios.append((grupo.chave, o.plataforma, o.id_produto, msg))


@pytest.fixture
def ciclo(monkeypatch):
    for nome in ("_proxima", "_proxima_shopee", "_loja_da_vez"):
        monkeypatch.setattr(pipeline, nome, {})
    monkeypatch.setattr(pipeline, "_avisou_shopee", set())
    monkeypatch.setattr(config, "fonte_ml", {"ativa": True})
    monkeypatch.setattr(config, "fonte_shopee", {"ativa": True})
    monkeypatch.setattr(config, "shopee_app_id", "id")
    monkeypatch.setattr(config, "shopee_app_secret", "segredo")
    monkeypatch.setattr(config, "max_posts_por_ciclo", 1)
    monkeypatch.setattr(config, "desconto_minimo", 0)
    monkeypatch.setattr(config, "preco_minimo", 0)
    monkeypatch.setattr(config, "preco_maximo", 0)
    monkeypatch.setattr(config, "palavras_bloqueadas", [])
    monkeypatch.setattr(config, "nao_repetir_dias", 7)
    monkeypatch.setattr(config, "cupons", ConfigCupons())
    monkeypatch.setattr(pipeline, "dentro_do_horario", lambda: True)

    def gerar(lista):
        for o in lista:
            o.url_afiliado = "https://meli.la/" + o.id_produto
    monkeypatch.setattr(pipeline.afiliado_ml, "gerar_links_afiliado", gerar)
    return Destino()


def _of(id_, titulo, plataforma="mercadolivre", desconto=40):
    o = Oferta(plataforma, id_, titulo, f"https://x/{id_}", 60, 100, desconto_pct=desconto)
    if plataforma == "shopee":
        o.url_afiliado = f"https://s.shopee.com.br/{id_}"
    return o


# ── R1: sem internet ─────────────────────────────────────────────────

def test_sem_internet_para_o_ciclo(monkeypatch, ciclo):
    monkeypatch.setattr(pipeline, "rede_ok", lambda: False)
    with pytest.raises(pipeline.SemInternet):
        pipeline.executar_ciclo(ciclo, [Grupo("g", "G", {"C1": "x"})])
    assert ciclo.envios == []


def test_internet_cai_no_meio_do_ciclo(monkeypatch, ciclo):
    rede = iter([True, False])  # ok no começo; a coleta vem vazia e a rede caiu
    monkeypatch.setattr(pipeline, "rede_ok", lambda: next(rede))
    monkeypatch.setattr(pipeline, "coletar", lambda cats: [])
    with pytest.raises(pipeline.SemInternet):
        pipeline.executar_ciclo(ciclo, [Grupo("g", "G", {"C1": "x", "C2": "y", "C3": "z"})])


def test_fora_do_horario_nem_testa_a_rede(monkeypatch, ciclo):
    monkeypatch.setattr(pipeline, "dentro_do_horario", lambda: False)
    monkeypatch.setattr(pipeline, "rede_ok", lambda: False)
    assert pipeline.executar_ciclo(ciclo, [Grupo("g", "G", {"C1": "x"})]) == 0


# ── R2: verificação de segurança na página de ofertas ────────────────

def test_verificacao_pausa_a_pagina_de_ofertas(monkeypatch, caplog):
    html = "<html><head><title>Segurança — Mercado Livre</title></head><body></body></html>"
    abertas = []

    def navegador(urls):
        abertas.extend(urls)
        return {u: html for u in urls}
    monkeypatch.setattr(ml_pagina, "_html_navegador", navegador)
    assert ml_pagina.buscar_ofertas({"MLB1": "A"}, navegador="sempre") == []
    assert ml_pagina.pausada()
    assert sum("verificação de segurança" in r.message for r in caplog.records) == 1
    # enquanto pausada, nem abre o Chrome
    assert ml_pagina.buscar_ofertas({"MLB2": "B"}, navegador="sempre") == []
    assert len(abertas) == 1


# ── R3: Linkbuilder interrompido por navegação ───────────────────────

class _PaginaFalsa:
    url = afiliado_ml.URL_LINKBUILDER

    def __init__(self, falhas):
        self.falhas, self.idas = falhas, 0

    def goto(self, *a, **k):
        self.idas += 1

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js, args):
        if self.falhas:
            self.falhas -= 1
            raise RuntimeError("Page.evaluate: Execution context was destroyed, most likely because of a navigation.")
        return {"http": 200, "dados": {"urls": [{"short_url": "https://meli.la/" + u[-1]} for u in args["urls"]]}}


def test_linkbuilder_recarrega_e_tenta_de_novo(monkeypatch):
    pagina = _PaginaFalsa(falhas=1)

    @contextmanager
    def chrome():
        yield pagina
    monkeypatch.setattr(afiliado_ml, "pagina_chrome", chrome)
    monkeypatch.setattr(afiliado_ml, "tem_sessao", lambda: True)
    monkeypatch.setattr(config, "ml_etiqueta", "tag")
    ofertas = [Oferta("mercadolivre", "1", "x", "https://ml/1"), Oferta("mercadolivre", "2", "y", "https://ml/2")]
    assert afiliado_ml.gerar_links_afiliado(ofertas) == 2
    assert [o.url_afiliado for o in ofertas] == ["https://meli.la/1", "https://meli.la/2"]
    assert pagina.idas == 2  # abriu de novo o Linkbuilder


# ── R4: Shopee ───────────────────────────────────────────────────────

class _Resp:
    def __init__(self, dados, status=200):
        self.dados, self.status_code, self.text = dados, status, str(dados)

    def json(self):
        return self.dados


def test_shopee_tenta_de_novo_no_erro_10000(monkeypatch):
    respostas = [_Resp({"errors": [{"message": "System Error", "extensions": {"code": 10000}}]}),
                 _Resp({"data": {"ok": 1}})]
    monkeypatch.setattr(shopee.requests, "post", lambda *a, **k: respostas.pop(0))
    monkeypatch.setattr(shopee.time, "sleep", lambda s: None)
    monkeypatch.setattr(config, "shopee_app_id", "id")
    monkeypatch.setattr(config, "shopee_app_secret", "s")
    assert shopee.chamar("{}") == {"ok": 1}


def test_shopee_desiste_depois_de_3_tentativas_e_nao_repete_erro_de_verdade(monkeypatch):
    chamadas = []

    def post(*a, **k):
        chamadas.append(1)
        return _Resp({"errors": [{"message": "System Error", "extensions": {"code": 10000}}]})
    monkeypatch.setattr(shopee.requests, "post", post)
    monkeypatch.setattr(shopee.time, "sleep", lambda s: None)
    monkeypatch.setattr(config, "shopee_app_id", "id")
    monkeypatch.setattr(config, "shopee_app_secret", "s")
    with pytest.raises(ErroShopee):
        shopee.chamar("{}")
    assert len(chamadas) == 3
    chamadas.clear()
    monkeypatch.setattr(shopee.requests, "post", lambda *a, **k: chamadas.append(1) or _Resp({}, 401))
    with pytest.raises(ErroShopee):
        shopee.chamar("{}")
    assert len(chamadas) == 1  # erro que não é passageiro: não insiste


def test_erro_na_shopee_tenta_a_proxima_palavra(monkeypatch, ciclo):
    def buscar(termo):
        if termo == "a":
            raise ErroShopee("Shopee API: System Error", passageiro=True)
        return [_of(termo, f"Produto {termo}", "shopee")]
    monkeypatch.setattr(pipeline.shopee, "buscar", buscar)
    monkeypatch.setattr(pipeline, "coletar", lambda cats: [_of("M", "Mercado")])
    g = Grupo("g", "G", {"C1": "x"}, shopee=["a", "b"])
    pipeline._loja_da_vez["g"] = 1  # vez da Shopee
    pipeline.executar_ciclo(ciclo, [g], registrar=False)
    assert [e[1:3] for e in ciclo.envios] == [("shopee", "b")]


def test_shopee_fora_guarda_a_vez_para_o_proximo_ciclo(monkeypatch, ciclo, caplog):
    falhar = [True]

    def buscar(termo):
        if falhar[0]:
            raise ErroShopee("Shopee API: System Error", passageiro=True)
        return [_of(termo, f"Produto {termo}", "shopee")]
    monkeypatch.setattr(pipeline.shopee, "buscar", buscar)
    monkeypatch.setattr(pipeline, "coletar", lambda cats: [_of(next(iter(cats)), "Item " + next(iter(cats)))])
    g = Grupo("g", "G", {"C1": "x", "C2": "y"}, shopee=["a"])
    pipeline._loja_da_vez["g"] = 1  # vez da Shopee (proporção 1:1)
    pipeline.executar_ciclo(ciclo, [g], registrar=False)
    falhar[0] = False
    pipeline.executar_ciclo(ciclo, [g], registrar=False)
    assert [e[1] for e in ciclo.envios] == ["mercadolivre", "shopee"]
    assert any("vez da Shopee fica para o próximo" in r.message for r in caplog.records)


def test_resumo_diario_da_shopee(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(pipeline, "_estat_shopee", {"dia": "", "ok": 0, "erro": 0, "resumido": False})
    pipeline._contar_shopee(True)
    pipeline._contar_shopee(False)
    pipeline._contar_shopee(False)
    pipeline.resumo_shopee()
    pipeline.resumo_shopee()  # uma vez por dia
    linhas = [r.message for r in caplog.records if "buscas ok" in r.message]
    assert len(linhas) == 1 and "1 buscas ok, 2 com erro da Shopee" in linhas[0]


# ── anti-repetição e rodízio espalhado ───────────────────────────────

def test_parecida_e_modelos():
    assert pipeline.parecida("Kit Shampoo Automotivo Vonixx V-Floc 500ml",
                             ["Shampoo Automotivo Neutro V Floc Concentrado 3l Vonixx"])
    assert not pipeline.parecida("Cera Automotiva Vitrificadora Blend Vonixx",
                                 ["Aspirador Automotivo Portátil WAP CAR Filtro HEPA"])
    assert pipeline.modelos("Processador Stetsom STX 2448 Floating") == {"stx2448"}
    assert pipeline.modelos("Processador de Áudio Digital Automotivo Stetsom STX2448 com") == {"stx2448"}
    assert pipeline.modelos("Kit 10 Panos 60x40cm 500ml 110v 200W 3l") == set()


def test_mesmo_modelo_em_outro_anuncio_conta_como_ja_enviado(ciclo):
    db.registrar(_of("A", "Processador Stetsom STX 2448 Floating Digital"), "g")
    motivos = pipeline.Counter()
    novas = pipeline.filtrar([_of("B", "Processador de Áudio Automotivo Stetsom STX2448"),
                              _of("C", "Amplificador Taramps TL500")], "g", [], motivos)
    assert [o.id_produto for o in novas] == ["C"] and motivos["já enviadas"] == 1


def test_pula_categoria_so_com_produto_parecido(monkeypatch, ciclo):
    db.registrar(_of("X", "Shampoo Automotivo V-Floc Vonixx 1,5l"), "g")
    por_cat = {"C1": [_of("A", "Kit Shampoo Vonixx V-Floc V-Mol")], "C2": [_of("B", "Aspirador Portátil WAP")]}
    monkeypatch.setattr(pipeline, "coletar", lambda cats: list(por_cat[next(iter(cats))]))
    pipeline.executar_ciclo(ciclo, [Grupo("g", "G", {"C1": "a", "C2": "b"})], registrar=False)
    assert [e[2] for e in ciclo.envios] == ["B"]


def test_se_tudo_for_parecido_manda_mesmo_assim(monkeypatch, ciclo):
    db.registrar(_of("X", "Shampoo Automotivo V-Floc Vonixx 1,5l"), "g")
    monkeypatch.setattr(pipeline, "coletar", lambda cats: [_of("A", "Kit Shampoo Vonixx V-Floc V-Mol")])
    pipeline.executar_ciclo(ciclo, [Grupo("g", "G", {"C1": "a"})], registrar=False)
    assert [e[2] for e in ciclo.envios] == ["A"]


def test_ordem_espalhada():
    assert pipeline.ordem_espalhada(4) == [0, 2, 1, 3]
    assert pipeline.ordem_espalhada(5) == [0, 3, 1, 4, 2]
    assert pipeline.ordem_espalhada(1) == [0]
    assert sorted(pipeline.ordem_espalhada(18)) == list(range(18))


def test_rodizio_intercala_as_metades_da_lista(monkeypatch, ciclo):
    monkeypatch.setattr(pipeline, "coletar", lambda cats: [_of(next(iter(cats)), "Item " + next(iter(cats)))])
    g = Grupo("g", "G", {"L1": "limpeza", "L2": "cera", "R1": "camiseta", "R2": "tênis"})
    for _ in range(4):
        pipeline.executar_ciclo(ciclo, [g], registrar=False)
    assert [e[2] for e in ciclo.envios] == ["L1", "R1", "L2", "R2"]


# ── cupons ───────────────────────────────────────────────────────────

AGORA = dt.datetime(2026, 11, 20, 15, 5)


def test_ler_cupons_do_config():
    c = cfg.ler_cupons({"horarios": ["20:00", "10:00"], "shopee_campanhas": True,
                        "lista": [{"descricao": "R$ 20 OFF", "codigo": "X", "link": "https://meli.la/a",
                                   "validade": dt.date(2026, 11, 30), "grupos": ["g"]},
                                  {"descricao": "sem link"}]})
    assert c.horarios == ["10:00", "20:00"] and c.shopee_campanhas
    assert c.lista == [Cupom("R$ 20 OFF", "https://meli.la/a", "X", "2026-11-30", ["g"])]
    assert cfg.ler_cupons({}).horarios == ["10:00", "15:00", "20:00"] and not cfg.ler_cupons({}).ligado


def test_cupom_do_painel_no_horario(monkeypatch, ciclo):
    monkeypatch.setattr(config, "cupons", ConfigCupons(
        horarios=["10:00", "15:00", "20:00"],
        lista=[Cupom("R$ 20 OFF acima de R$ 99", "https://meli.la/abc", "APROVEITA", "2026-11-30")]))
    g = Grupo("g", "G", {"C1": "x"}, convite="https://chat.whatsapp.com/X")
    [post] = cupons.da_vez([g], AGORA)
    assert post.horarios == ["10:00", "15:00"]  # o bot ligou às 15h: um post só cobre os dois
    assert post.mensagem.startswith("*🎟️ CUPOM LIBERADO NO MERCADO LIVRE*\n\nR$ 20 OFF acima de R$ 99")
    assert "🏷️ Código: *APROVEITA*\n⏰ Válido até 30/11" in post.mensagem
    assert "*🛒 Use aqui no Mercado Livre:*\nhttps://meli.la/abc" in post.mensagem
    cupons.registrar(post, AGORA)
    assert cupons.da_vez([g], AGORA) == []  # já cumpriu os horários de hoje
    assert cupons.da_vez([g], AGORA.replace(hour=20)) != []


def test_cupom_vencido_ou_de_outro_grupo_nao_sai(monkeypatch, ciclo, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config, "cupons", ConfigCupons(horarios=["10:00"], lista=[
        Cupom("Vencido", "https://meli.la/a", validade="2026-11-19"),
        Cupom("Outro grupo", "https://meli.la/b", grupos=["outro"])]))
    g = Grupo("g", "G", {"C1": "x"})
    assert cupons.da_vez([g], AGORA) == []
    assert any("nenhum cupom válido" in r.message for r in caplog.records)
    assert cupons.da_vez([g], AGORA) == []  # o horário ficou registrado: não insiste a cada ciclo


def test_cupom_sem_link_de_afiliado_nao_sai(monkeypatch, ciclo):
    monkeypatch.setattr(config, "cupons", ConfigCupons(horarios=["10:00"], lista=[
        Cupom("Página", "https://www.mercadolivre.com.br/cupons")]))

    def gerar(lista):
        raise afiliado_ml.ErroAfiliado("URL not allowed in affiliates program")
    monkeypatch.setattr(cupons.afiliado_ml, "gerar_links_afiliado", gerar)
    assert cupons.da_vez([Grupo("g", "G", {"C1": "x"})], AGORA) == []


def test_cupom_da_shopee_vira_link_de_afiliado(monkeypatch, ciclo):
    monkeypatch.setattr(config, "cupons", ConfigCupons(horarios=["10:00"], lista=[
        Cupom("Frete grátis", "https://shopee.com.br/m/cupons")]))
    monkeypatch.setattr(cupons.shopee, "link_afiliado", lambda url: "https://s.shopee.com.br/curto")
    [post] = cupons.da_vez([Grupo("g", "G", {"C1": "x"})], AGORA)
    assert "*🛒 Use aqui na Shopee:*\nhttps://s.shopee.com.br/curto" in post.mensagem


def test_rodizio_entre_cupons_do_painel(monkeypatch, ciclo):
    monkeypatch.setattr(config, "cupons", ConfigCupons(horarios=["10:00", "15:00"], lista=[
        Cupom("Primeiro", "https://meli.la/1"), Cupom("Segundo", "https://meli.la/2")]))
    g = Grupo("g", "G", {"C1": "x"})
    [p1] = cupons.da_vez([g], AGORA.replace(hour=10))
    cupons.registrar(p1, AGORA.replace(hour=10))
    [p2] = cupons.da_vez([g], AGORA)
    assert (p1.oferta.titulo, p2.oferta.titulo) == ("Primeiro", "Segundo")


def test_campanha_da_shopee_quando_nao_ha_cupom(monkeypatch, ciclo):
    monkeypatch.setattr(config, "cupons", ConfigCupons(horarios=["10:00"], shopee_campanhas=True))
    fim = dt.datetime(2026, 11, 20, 23, 59).timestamp()
    monkeypatch.setattr(cupons.shopee, "campanhas", lambda: [
        {"nome": "Campanha 11.11", "link": "https://s.shopee.com.br/c", "imagem": "https://img", "fim": fim}])
    g = Grupo("g", "G", {"C1": "x"})
    [post] = cupons.da_vez([g], AGORA)
    assert post.mensagem.startswith("*🎟️ CUPONS LIBERADOS NA SHOPEE*\n\nCampanha 11.11\n⏰ Válido até 20/11 às 23h59")
    assert post.oferta.imagem == "https://img"
    cupons.registrar(post, AGORA)
    # a mesma campanha não volta no dia seguinte (REPETIR_CAMPANHA_DIAS)
    assert cupons.da_vez([g], AGORA + dt.timedelta(days=1)) == []


def test_campanhas_da_shopee_so_para_os_grupos_marcados(monkeypatch, ciclo):
    monkeypatch.setattr(config, "cupons", ConfigCupons(horarios=["10:00"], shopee_campanhas=True,
                                                       grupos_campanhas=["outro"]))
    monkeypatch.setattr(cupons.shopee, "campanhas", lambda: [{"nome": "C", "link": "https://s.shopee.com.br/c",
                                                              "imagem": None, "fim": None}])
    assert cupons.da_vez([Grupo("g", "G", {"C1": "x"})], AGORA) == []


def test_ciclo_envia_cupom_depois_das_ofertas(monkeypatch, ciclo):
    monkeypatch.setattr(config, "cupons", ConfigCupons(horarios=["00:00"], lista=[Cupom("R$ 10 OFF", "https://meli.la/z")]))
    monkeypatch.setattr(pipeline, "coletar", lambda cats: [_of("A", "Aspirador Portátil")])
    g = Grupo("g", "G", {"C1": "x"})
    assert pipeline.executar_ciclo(ciclo, [g]) == 1
    assert [e[2] for e in ciclo.envios] == ["A", Cupom("R$ 10 OFF", "https://meli.la/z").ident]
    pipeline.executar_ciclo(ciclo, [g])
    assert sum(e[2].startswith("cupom:") for e in ciclo.envios) == 1  # cupom só uma vez por horário


def test_campanhas_da_api_ignora_vencidas(monkeypatch):
    agora = dt.datetime.now().timestamp()
    monkeypatch.setattr(shopee, "chamar", lambda q: {"shopeeOfferV2": {"nodes": [
        {"offerName": "Vale", "offerLink": "https://s/1", "periodEndTime": agora + 3600, "periodStartTime": agora - 10},
        {"offerName": "Vencida", "offerLink": "https://s/2", "periodEndTime": agora - 10},
        {"offerName": "Sem link"}]}})
    assert [c["nome"] for c in shopee.campanhas()] == ["Vale"]
