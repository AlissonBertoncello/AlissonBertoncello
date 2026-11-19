"""P1 (página de ofertas desligada), P2 (departamentos escolhidos, ranking no nível certo,
categoria sem ranking anotada) e IA1 (Claude pesquisa, a API do ML confere)."""
import datetime as dt
import json
from types import SimpleNamespace as NS

import pytest

from ofertas import painel, pipeline
from ofertas.config import config
from ofertas.models import ConfigCupons, Grupo, Oferta
from ofertas.sources import ia_ofertas as ia
from ofertas.sources import mercadolivre, ml_geral
from ofertas.sources.mercadolivre import ErroAPI

T = dt.datetime(2026, 11, 19, 10, 0).timestamp()


@pytest.fixture(autouse=True)
def sem_bloqueio_geral(monkeypatch):
    """Não depende das palavras bloqueadas do config.yaml local."""
    monkeypatch.setattr(config, "palavras_bloqueadas", [])
    monkeypatch.setattr(config, "marcas_boas", [])

RAIZ_ML = [{"id": "MLB1430", "name": "Calçados, Roupas e Bolsas"}, {"id": "MLB1403", "name": "Alimentos e Bebidas"},
           {"id": "MLB1246", "name": "Beleza e Cuidado Pessoal"}, {"id": "MLB3937", "name": "Joias e Relógios"},
           {"id": "MLB1196", "name": "Livros, Revistas e Comics"}, {"id": "MLB1000", "name": "Eletrônicos, Áudio e Vídeo"},
           {"id": "MLB1459", "name": "Imóveis"}]


# ── P2: departamentos ───────────────────────────────────────────────

def test_departamentos_escolhidos_sem_comida_nem_livros():
    deps = ml_geral.escolher_departamentos(RAIZ_ML)
    assert set(deps) == {"MLB1430", "MLB1246", "MLB3937", "MLB1000"}
    assert deps.count("MLB1430") == 2  # moda e calçados com peso 2
    assert deps[0] != deps[1]  # repetição espalhada


def test_sem_departamento_conhecido_usa_todos_de_varejo():
    assert ml_geral.escolher_departamentos([{"id": "A", "name": "Novidade"}, {"id": "B", "name": "Imóveis"}]) == ["A"]


def test_departamentos_do_painel_continuam_valendo():
    g = Grupo("g", "G", ofertas_gerais=True, departamentos={"MLB1246": "Beleza"})
    assert ml_geral._departamentos(g, object()) == ["MLB1246"]


class ClienteArvore:
    def __init__(self):
        self.destaques_pedidos = []

    def categoria(self, cid):
        arvore = {"DEP": [{"id": "CAL", "name": "Calçados"}, {"id": "REL", "name": "Relógios"}],
                  "CAL": [{"id": "TEN", "name": "Tênis"}, {"id": "BOT", "name": "Botas"}],
                  "REL": [{"id": "PUL", "name": "Relógios de Pulso"}]}
        return {"children_categories": arvore.get(cid, [])}

    def destaques(self, site, cid):
        self.destaques_pedidos.append(cid)
        raise ErroAPI(f"GET /highlights/MLB/category/{cid} respondeu HTTP 404: not found")


def test_ranking_no_primeiro_nivel_e_nomes_do_segundo_alternando():
    itens = ml_geral.itens_do_departamento("DEP", ClienteArvore())
    # ranking pela subcategoria do 1º nível; nome do 2º nível para o catálogo; alterna CAL/REL
    assert itens == [("CAL", "Tênis"), ("REL", "Relógios de Pulso"), ("CAL", "Botas")]


def test_categoria_sem_ranking_fica_anotada():
    c = ClienteArvore()
    assert ml_geral.mais_vendidos("CAL", c) == []
    assert ml_geral.mais_vendidos("CAL", c) == []
    assert c.destaques_pedidos == ["CAL"]  # o 404 não é pedido de novo
    assert "CAL" in json.loads(ml_geral.ARQ_TERMOS.read_text(encoding="utf-8"))["_sem_ranking"]["termos"]


def test_outro_erro_do_ranking_continua_sendo_erro():
    class Fora(ClienteArvore):
        def destaques(self, site, cid):
            raise ErroAPI("HTTP 500")
    with pytest.raises(ErroAPI):
        ml_geral.mais_vendidos("CAL", Fora())


# ── IA: limites e custo ─────────────────────────────────────────────

def _ligar_ia(monkeypatch, **op):
    monkeypatch.setattr(config, "anthropic_api_key", "sk-ant-teste")
    monkeypatch.setattr(config, "fonte_ia", {"ativa": True, **op})


def test_ia_desligada_por_padrao():
    assert not ia.ligada()
    assert ia.motivo_para_nao_buscar(T) == "desligada"


def test_ia_sem_chave_nao_busca(monkeypatch):
    monkeypatch.setattr(config, "fonte_ia", {"ativa": True})
    assert ia.motivo_para_nao_buscar(T) == "sem ANTHROPIC_API_KEY no .env"


def test_estimativa_de_custo():
    op = {**ia.opcoes(), "modelo": "claude-opus-5-5", "pesquisas_por_busca": 5, "buscas_por_dia": 3,
          "gasto_max_mes_usd": 0}
    c = ia.estimativa(op)
    # 43 mil tokens lidos a US$ 4/milhão + 4 mil escritos a US$ 20/milhão + 5 pesquisas a US$ 0,01
    assert c["por_busca"] == pytest.approx(0.172 + 0.08 + 0.05, abs=0.001)
    assert c["por_mes"] == pytest.approx(c["por_busca"] * 90, abs=0.05)
    assert ia.estimativa({**op, "gasto_max_mes_usd": 10})["por_mes"] == 10


def test_limites_por_dia_intervalo_e_gasto(monkeypatch):
    _ligar_ia(monkeypatch, buscas_por_dia=2, intervalo_horas=4, gasto_max_mes_usd=1)
    assert ia.motivo_para_nao_buscar(T) is None
    ia._registrar_busca(0.30, T)
    assert "intervalo" in ia.motivo_para_nao_buscar(T + 3600)
    assert ia.motivo_para_nao_buscar(T + 5 * 3600) is None
    ia._registrar_busca(0.30, T + 5 * 3600)
    assert "2 buscas por dia" in ia.motivo_para_nao_buscar(T + 10 * 3600)
    amanha = T + 24 * 3600
    assert ia.motivo_para_nao_buscar(amanha) is None
    ia._registrar_busca(0.50, amanha)
    assert "gasto do mês" in ia.motivo_para_nao_buscar(amanha + 6 * 3600)
    assert ia.gasto_do_mes(hoje=dt.date(2026, 11, 20)) == pytest.approx(1.10)


# ── IA: pedido ao Claude (falso) ────────────────────────────────────

def _uso(entrada=40000, saida=3000, pesquisas=4):
    return NS(input_tokens=entrada, output_tokens=saida, cache_creation_input_tokens=0,
              cache_read_input_tokens=0, server_tool_use=NS(web_search_requests=pesquisas))


class Claude:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.pedidos = []
        self.beta = NS(messages=NS(create=self._create))
        self.messages = NS(create=self._create)

    def _create(self, **pedido):
        self.pedidos.append(pedido)
        return self.respostas.pop(0)


SUGESTOES = [
    {"url": "https://produto.mercadolivre.com.br/MLB-1234567890-tenis-nike-_JM", "titulo": "Tênis Nike",
     "preco": 199.9, "preco_original": 399.9},
    {"url": "https://www.mercadolivre.com.br/relogio-casio/p/MLB22334455", "titulo": "Relógio Casio",
     "preco": 150, "preco_original": 300},
    {"url": "https://produto.mercadolivre.com.br/MLB-9999999999-inventado-_JM", "titulo": "Inventado",
     "preco": 10, "preco_original": 100},
]


def _resposta_final():
    return NS(stop_reason="tool_use", usage=_uso(), content=[
        NS(type="text", text="Achei estas."),
        NS(type="tool_use", name="entregar_ofertas", input={"ofertas": SUGESTOES})])


def test_pede_com_pesquisa_na_web_e_continua_pesquisa_longa(monkeypatch):
    _ligar_ia(monkeypatch)
    claude = Claude([NS(stop_reason="pause_turn", usage=_uso(10000, 500, 2), content=[NS(type="text", text="...")]),
                     _resposta_final()])
    monkeypatch.setattr(ia, "_cliente", lambda: claude)
    sugestoes, uso = ia.pedir_sugestoes()
    assert [s["titulo"] for s in sugestoes] == ["Tênis Nike", "Relógio Casio", "Inventado"]
    assert len(claude.pedidos) == 2 and claude.pedidos[1]["messages"][-1]["role"] == "assistant"
    p = claude.pedidos[0]
    assert p["model"] == "claude-opus-5-5"
    pesquisa = next(t for t in p["tools"] if t["name"] == "web_search")
    assert pesquisa["type"] == "web_search_20260209" and pesquisa["max_uses"] == 5
    assert "mercadolivre.com.br" in pesquisa["allowed_domains"]
    assert uso["pesquisas"] == 6 and uso["custo"] == pytest.approx(
        ia.custo_real("claude-opus-5-5", 50000, 3500, 6))


def test_haiku_usa_a_pesquisa_basica(monkeypatch):
    _ligar_ia(monkeypatch, modelo="claude-haiku-5-5")
    claude = Claude([_resposta_final()])
    monkeypatch.setattr(ia, "_cliente", lambda: claude)
    ia.pedir_sugestoes()
    assert claude.pedidos[0]["tools"][0]["type"] == "web_search_20250305"
    assert "fallbacks" not in claude.pedidos[0]


def test_lista_em_json_no_texto_tambem_vale():
    r = NS(content=[NS(type="text", text='Aqui: {"ofertas": [{"url": "u", "titulo": "t", "preco": 1, "preco_original": 0}]}')])
    assert ia._sugestoes_da_resposta(r)[0]["titulo"] == "t"


class ClienteML:
    def itens(self, ids):
        if ids == ["MLB1234567890"]:
            return [{"id": "MLB1234567890", "title": "Tênis Nike Revolution 7", "price": 189.9,
                     "original_price": 399.9, "permalink": "https://produto.mercadolivre.com.br/MLB-1234567890-x",
                     "thumbnail": "http://x/a-I.jpg"}]
        return []

    def produto(self, pid):
        if pid == "MLB22334455":
            return {"id": pid, "name": "Relógio Casio G-Shock", "buy_box_winner": {"price": 299.0, "original_price": 599.0}}
        raise ErroAPI("HTTP 404")

    def buscar_produtos(self, site, q, limite):
        return []


def test_so_fica_o_que_a_api_do_ml_confirma():
    ofertas, descartadas = ia.conferir(SUGESTOES, ClienteML())
    assert descartadas == 1
    por_id = {o.id_produto: o for o in ofertas}
    assert set(por_id) == {"MLB1234567890", "MLB22334455"}
    assert por_id["MLB1234567890"].preco == 189.9  # preço da API, não o da IA
    assert por_id["MLB22334455"].titulo == "Relógio Casio G-Shock"


def test_sem_link_procura_pelo_nome_e_confere_se_e_o_mesmo(monkeypatch):
    achados = [Oferta("mercadolivre", "MLB5", "Perfume Malbec Gold 100ml", "https://ml/5", 150, 250),
               Oferta("mercadolivre", "MLB6", "Furadeira Bosch", "https://ml/6", 200, 300)]
    monkeypatch.setattr(mercadolivre, "_via_catalogo", lambda c, site, q, n: achados)
    ok, ruins = ia.conferir([{"url": "https://pelando.com.br/x", "titulo": "Perfume Malbec Gold 100ml"},
                             {"url": "", "titulo": "Panela Tramontina"}], ClienteML())
    assert [o.id_produto for o in ok] == ["MLB5"] and ruins == 1


@pytest.fixture
def ciclo(monkeypatch):
    for nome in ("_proxima", "_proxima_shopee", "_loja_da_vez"):
        monkeypatch.setattr(pipeline, nome, {})
    monkeypatch.setattr(config, "fonte_ml", {"ativa": True})
    monkeypatch.setattr(config, "fonte_shopee", {"ativa": False})
    monkeypatch.setattr(config, "max_posts_por_ciclo", 1)
    monkeypatch.setattr(config, "desconto_minimo", 10)
    monkeypatch.setattr(config, "preco_minimo", 0)
    monkeypatch.setattr(config, "preco_maximo", 0)
    monkeypatch.setattr(config, "palavras_bloqueadas", [])
    monkeypatch.setattr(config, "cupons", ConfigCupons(horarios=[]))
    monkeypatch.setattr(pipeline, "dentro_do_horario", lambda: True)

    def gerar(lista, etiqueta=""):
        for o in lista:
            o.url_afiliado = f"https://meli.la/{o.id_produto}"
    monkeypatch.setattr(pipeline.afiliado_ml, "gerar_links_afiliado", gerar)

    class Destino:
        nome = "console"
        envios = []

        def enviar(self, o, msg, grupo):
            self.envios.append(o.id_produto)
    return Destino()


def test_ciclo_envia_oferta_achada_pela_ia_e_conferida(monkeypatch, ciclo):
    _ligar_ia(monkeypatch)
    claude = Claude([_resposta_final()])
    monkeypatch.setattr(ia, "_cliente", lambda: claude)
    monkeypatch.setattr(mercadolivre, "cliente_padrao", lambda: ClienteML())
    g = Grupo("clube", "Clube", ofertas_gerais=True)
    assert pipeline.executar_ciclo(ciclo, [g], registrar=False) == 1
    assert ciclo.envios[0] in {"MLB1234567890", "MLB22334455"}
    # no ciclo seguinte não pergunta de novo (intervalo), usa o estoque
    pipeline.executar_ciclo(ciclo, [g], registrar=False)
    assert len(claude.pedidos) == 1
    assert ia.ler_estado()["buscas_dia"] == {dt.date.today().isoformat(): 1}


def test_ciclo_sem_grupo_de_ofertas_gerais_nao_chama_a_ia(monkeypatch, ciclo):
    _ligar_ia(monkeypatch)
    monkeypatch.setattr(pipeline, "coletar", lambda cats: [])
    pipeline.executar_ciclo(ciclo, [Grupo("b", "B", {"MLB1": "x"})], registrar=False)  # _cliente falha se chamar


def test_erro_da_chave_nao_derruba_o_ciclo(monkeypatch, caplog):
    import anthropic
    import httpx2 as httpx  # mesmo pacote HTTP do SDK
    _ligar_ia(monkeypatch)

    class Recusa:
        def _create(self, **k):
            raise anthropic.AuthenticationError("invalid x-api-key", response=httpx.Response(
                401, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")), body=None)
    r = Recusa()
    r.beta = NS(messages=NS(create=r._create))
    monkeypatch.setattr(ia, "_cliente", lambda: r)
    assert ia.buscar(T) == []
    assert any("chave ANTHROPIC_API_KEY inválida" in x.message for x in caplog.records)
    assert ia.motivo_para_nao_buscar(T + 60) is not None  # não fica tentando à toa


# ── painel ──────────────────────────────────────────────────────────

@pytest.fixture
def arquivos(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path
    raiz = Path(__file__).resolve().parent.parent
    shutil.copy(raiz / "config.exemplo.yaml", tmp_path / "config.yaml")
    (tmp_path / ".env").write_text("ML_CLIENT_ID=1\n", encoding="utf-8")
    monkeypatch.setattr(painel, "ARQ_CONFIG", tmp_path / "config.yaml")
    monkeypatch.setattr(painel, "ARQ_ENV", tmp_path / ".env")
    monkeypatch.setattr(painel, "DATA_DIR", tmp_path)
    return tmp_path


def test_painel_le_e_grava_a_ia(arquivos):
    import yaml
    d = painel.ler_tudo()
    assert d["ia"]["ativa"] is False and d["ia"]["modelo"] == "claude-opus-5-5"
    assert d["env"]["ANTHROPIC_API_KEY"] == {"secreto": True, "definido": False, "valor": ""}
    assert d["ia_info"]["precos"]["claude-opus-5-5"] == [4.0, 20.0]
    d["env"] = {"ANTHROPIC_API_KEY": "sk-ant-xyz"}
    d["ia"].update(ativa=True, buscas_por_dia=2, gasto_max_mes_usd=5.5)
    assert painel.salvar(d) == []
    ia_yaml = yaml.safe_load((arquivos / "config.yaml").read_text(encoding="utf-8"))["fontes"]["ia"]
    assert ia_yaml["ativa"] is True and ia_yaml["buscas_por_dia"] == 2 and ia_yaml["gasto_max_mes_usd"] == 5.5
    assert "ANTHROPIC_API_KEY=sk-ant-xyz" in (arquivos / ".env").read_text(encoding="utf-8")
    assert painel.ler_tudo()["env"]["ANTHROPIC_API_KEY"]["valor"] == ""  # segredo não volta para a tela


def test_painel_valida_a_ia(arquivos):
    d = painel.ler_tudo()
    d["env"] = {}
    d["ia"].update(modelo="gpt-5", buscas_por_dia=99, intervalo_horas=0)
    erros = painel.salvar(d)
    assert any("modelo desconhecido" in e for e in erros)
    assert any("buscas_por_dia" in e for e in erros) and any("intervalo_horas" in e for e in erros)


def test_tela_mostra_custo_antes_de_ligar():
    html = painel.ARQ_HTML.read_text(encoding="utf-8")
    assert 'id="ia-custo"' in html and "Ligar a IA? Custo estimado" in html
    assert "ANTHROPIC_API_KEY" in html


# ── IA: aproveitar os links que vieram nas pesquisas (correção do teste F de 19/11) ──

def _mensagem_real(stop_reason="end_turn", com_links=True, texto="Pesquisei, mas não montei a lista."):
    """Resposta no formato real do SDK (BetaMessage), como a API devolve."""
    from anthropic.types.beta import BetaMessage
    resultados = [{"type": "web_search_result", "url": "https://lista.mercadolivre.com.br/tenis-nike",
                   "title": "Tênis Nike", "encrypted_content": "x", "page_age": None}]
    if com_links:
        resultados.insert(0, {"type": "web_search_result", "title": "Tênis Nike Revolution | Mercado Livre",
                              "url": "https://produto.mercadolivre.com.br/MLB-1234567890-tenis-nike-revolution-_JM",
                              "encrypted_content": "x", "page_age": None})
    return BetaMessage.model_validate({
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 40000, "output_tokens": 3000,
                  "server_tool_use": {"web_search_requests": 5, "web_fetch_requests": 0}},
        "content": [
            {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search",
             "input": {"query": "tênis nike oferta mercado livre"}},
            {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": resultados},
            {"type": "text", "text": texto, "citations": [
                {"type": "web_search_result_location", "title": "Relógio Casio",
                 "url": "https://www.mercadolivre.com.br/relogio-casio/p/MLB22334455",
                 "encrypted_index": "x", "cited_text": "..."}] if com_links else None}]})


def test_sem_lista_da_ia_usa_os_links_das_pesquisas(monkeypatch):
    _ligar_ia(monkeypatch)
    claude = Claude([_mensagem_real()])
    monkeypatch.setattr(ia, "_cliente", lambda: claude)
    sugestoes, uso = ia.pedir_sugestoes()
    assert len(claude.pedidos) == 1  # já tinha links: não pede de novo
    assert uso["da_lista"] == 0 and uso["das_pesquisas"] == 2
    ofertas, descartadas = ia.conferir(sugestoes, ClienteML())
    assert {o.id_produto for o in ofertas} == {"MLB1234567890", "MLB22334455"} and descartadas == 0
    diag = ia.ARQ_ULTIMA_RESPOSTA.read_text(encoding="utf-8")
    assert "lista da IA (entregar_ofertas): não veio" in diag and "MLB-1234567890" in diag


def test_sem_lista_e_sem_links_pede_so_a_lista_uma_vez(monkeypatch):
    _ligar_ia(monkeypatch)
    claude = Claude([_mensagem_real(com_links=False), _mensagem_real(com_links=False)])
    monkeypatch.setattr(ia, "_cliente", lambda: claude)
    sugestoes, uso = ia.pedir_sugestoes()
    assert sugestoes == [] and len(claude.pedidos) == 2  # uma vez só
    segundo = claude.pedidos[1]
    assert segundo["messages"][-1] == {"role": "user", "content": ia._PEDIDO_LISTA}
    assert next(t for t in segundo["tools"] if t["name"] == "web_search")["max_uses"] == 1


def test_lista_da_ia_e_links_das_pesquisas_somam_sem_repetir(monkeypatch):
    _ligar_ia(monkeypatch)
    m = _mensagem_real(stop_reason="tool_use")
    from anthropic.types.beta import BetaToolUseBlock
    m.content.append(BetaToolUseBlock(type="tool_use", id="toolu_1", name="entregar_ofertas", input={"ofertas": [
        {"url": "https://www.mercadolivre.com.br/relogio-casio/p/MLB22334455", "titulo": "Relógio Casio",
         "preco": 150, "preco_original": 300}]}))
    claude = Claude([m])
    monkeypatch.setattr(ia, "_cliente", lambda: claude)
    sugestoes, uso = ia.pedir_sugestoes()
    assert uso["da_lista"] == 1 and uso["das_pesquisas"] == 2
    from ofertas.afiliado_ml import extrair_id
    # a lista da IA primeiro; o relógio, que também veio nas pesquisas, não entra duas vezes
    assert [extrair_id(s["url"]) for s in sugestoes] == ["MLB22334455", "MLB1234567890"]


def test_pagina_de_lista_ou_de_outro_site_nao_e_produto():
    assert ia.links_das_pesquisas([{"url": "https://lista.mercadolivre.com.br/tenis"},
                                   {"url": "https://www.pelando.com.br/d/tenis-MLB123456789"}]) == []


def test_busca_que_nao_termina_aproveita_os_links(monkeypatch):
    _ligar_ia(monkeypatch)
    claude = Claude([_mensagem_real(stop_reason="pause_turn")] * (ia.CONTINUAR_MAX + 2))
    monkeypatch.setattr(ia, "_cliente", lambda: claude)
    sugestoes, uso = ia.pedir_sugestoes()
    assert uso["das_pesquisas"] == 2 and len(sugestoes) == 2


# ── G2: em alta no ML (termos mais buscados agora) ──────────────────

class ClienteTendencias:
    def __init__(self, recusa=False):
        self.pedidos = []
        self.recusa = recusa

    def get(self, caminho, params=None):
        self.pedidos.append(caminho)
        if self.recusa:
            raise ErroAPI(f"GET {caminho} respondeu HTTP 403: forbidden")
        return {"/trends/MLB/MLB1246": [{"keyword": "perfume masculino"}, {"keyword": "queratina"},
                                        {"keyword": "kit natal boticario"}, {"keyword": "protetor solar"}],
                "/trends/MLB/MLB1430": [{"keyword": "jordan"}, {"keyword": "snoopy"},
                                        {"keyword": "tenis nike air"}, {"keyword": "Perfume Masculino"}],
                "/trends/MLB": [{"keyword": "black friday"}, {"keyword": "gta 6"}]}.get(caminho, [])


def test_termos_em_alta_dos_departamentos_sem_termos_fracos():
    g = Grupo("g", "G", ofertas_gerais=True, departamentos={"MLB1246": "Beleza", "MLB1430": "Moda"})
    c = ClienteTendencias()
    # sem a lista geral; sem palavra solta (queratina, snoopy), sem data (natal); marca solta vale
    assert ml_geral.termos_em_alta(g, c) == ["perfume masculino", "jordan", "tenis nike air", "protetor solar"]
    ml_geral.termos_em_alta(g, c)
    assert c.pedidos == ["/trends/MLB/MLB1246", "/trends/MLB/MLB1430"]  # guardado por 6 h
    assert ml_geral.em_alta_da_vez(g, c) == ["perfume masculino", "jordan"]
    assert ml_geral.em_alta_da_vez(g, c) == ["tenis nike air", "protetor solar"]


def test_termo_com_palavra_bloqueada_do_grupo_fica_de_fora():
    g = Grupo("g", "G", ofertas_gerais=True, bloquear=["protetor"])
    assert not ml_geral.termo_bom("protetor solar", g) and ml_geral.termo_bom("perfume masculino", g)


def test_lista_em_alta_recusada_avisa_uma_vez(caplog):
    g = Grupo("g", "G", ofertas_gerais=True, departamentos={"MLB1246": "Beleza"})
    c = ClienteTendencias(recusa=True)
    assert ml_geral.termos_em_alta(g, c) == [] and ml_geral.termos_em_alta(g, c) == []
    assert len(c.pedidos) == 1
    assert sum("mais buscados" in r.message for r in caplog.records) == 1


def test_em_alta_so_de_reserva_quando_os_rankings_nao_tem_nada(monkeypatch, ciclo):
    monkeypatch.setattr(mercadolivre, "cliente_padrao", lambda: object())
    monkeypatch.setattr(ml_geral, "da_vez", lambda g, c: [("MLB9", "Mochilas")])
    monkeypatch.setattr(ml_geral, "em_alta_da_vez", lambda g, c: ["perfume masculino"])
    buscados = []

    def catalogo(termo, cliente, limite=10):
        buscados.append((termo, limite))
        if termo == "perfume masculino":
            return [Oferta("mercadolivre", "MLB71", "Perfume Masculino Malbec 100ml", "https://ml/71", 150, 250, posicao=1)]
        return []
    monkeypatch.setattr(ml_geral, "catalogo", catalogo)
    monkeypatch.setattr(ml_geral, "mais_vendidos", lambda cid, c: buscados.append(cid) or [])
    pipeline.executar_ciclo(ciclo, [Grupo("geral", "Geral", ofertas_gerais=True)], registrar=False)
    assert buscados == ["MLB9", ("Mochilas", 10), ("perfume masculino", 30)]
    assert ciclo.envios[-1] == "MLB71"


# ── Q4/Q5: nota de qualidade e pisos do grupo ───────────────────────

def _o(id_, titulo, preco, original, posicao=None, marca=None):
    return Oferta("mercadolivre", id_, titulo, f"https://ml/{id_}", preco, original, posicao=posicao, marca=marca)


# produtos que apareceram de verdade nos testes e no log de 19/11
REAIS = [
    _o("1", "Escova Rotativa Mondial Ceramica Tourmaline Ion 3x1 Erb-01", 139.00, 302.17, 3),
    _o("2", "Prancha Philco PPR10 Titanium Digital Bivolt 230°C", 142.04, 267.99, 5),
    _o("3", "Secador de Cabelo Gama Italy Eleganza Plus 2100W Ceramic Ion", 141.00, 238.98, 8),
    _o("4", "Óculos de Sol Saint Germain Siena Oval Tartaruga para Mulher", 69.90, 183.95, 1),
    _o("5", "Caixa Porta Relógios 6 Lugares Maleta Com Estojo Organizador", 42.99, 110.23, 2),
    _o("6", "Guarda Chuva Abre E Fecha Automático Reforçado Contra Vento", 35.64, 69.88, 4),
    _o("7", "Funko Pop! Calendario Advento - O Estranho Mundo De Jack", 335.00, 408.54),
    _o("8", "Graxa Unilit Blue 1KG - GRAXA AZUL", 38.53, 42.81),
    _o("9", "Balança Digital Utensílio BALANÇA DIGITAL 50 kg Portátil", 24.78, 35.91),
    _o("10", "Gravata Masculina Premium Tradicional Padrinhos Casamento", 17.74, 33.47, 6),
    _o("11", "40 Peças / 46 Peças Jogo De Chave Catraca Caixa De Ferramentas", 28.99, 87.85),
]


def test_pisos_do_grupo_de_ofertas_gerais_cortam_o_fraco():
    from ofertas import config as cfg
    [g] = cfg.ler_grupos({"clube": {"ofertas_gerais": True}})
    assert (g.desconto_minimo, g.preco_minimo) == (25, 25.0)
    boas = {o.id_produto for o in pipeline.filtrar_do_grupo(g, REAIS)}
    assert boas == {"1", "2", "3", "4", "5", "6", "11"}  # sai Funko, graxa, balança, gravata
    [comum] = cfg.ler_grupos({"mulher": {"categorias": {"MLB1": "x"}}})
    assert (comum.desconto_minimo, comum.preco_minimo) == (None, None)  # vale o de filtros
    [proprio] = cfg.ler_grupos({"c": {"ofertas_gerais": True, "desconto_minimo": 40, "preco_minimo": 0}})
    assert (proprio.desconto_minimo, proprio.preco_minimo) == (40, 0.0)


def test_nota_poe_as_marcas_na_frente():
    g = Grupo("clube", "Clube", ofertas_gerais=True, desconto_minimo=25, preco_minimo=25)
    ordem = [o.id_produto for o in pipeline.escolher_do_grupo(g, pipeline.filtrar_do_grupo(g, REAIS), 10)]
    assert set(ordem[:3]) == {"1", "2", "3"}  # Mondial, Philco, Gama Italy
    assert ordem.index("11") > 2 and ordem.index("6") > 2


def test_marca_da_ficha_do_ml_tambem_vale():
    from ofertas import qualidade
    assert qualidade.marca_boa(_o("x", "Tênis Esportivo Masculino Corrida", 199, 399, marca="Olympikus")) == "olympikus"
    assert qualidade.marca_boa(_o("y", "Tênis Esportivo Masculino Corrida", 199, 399, marca="Genérica")) is None
    assert qualidade.marca_boa(_o("z", "Fone JBL Tune 520BT", 199, 399)) == "jbl"


def test_marcas_extras_do_painel(monkeypatch):
    from ofertas import qualidade
    monkeypatch.setattr(config, "marcas_boas", ["Saint Germain"])
    assert qualidade.marca_boa(REAIS[3]) == "saint germain"


def test_grupo_comum_continua_pelo_desconto():
    g = Grupo("mulher", "Mulher")
    ordem = [o.id_produto for o in pipeline.escolher_do_grupo(g, REAIS[:6], 6)]
    assert ordem[0] == "4"  # maior desconto (62%), sem nota


def test_ciclo_junta_os_rankings_e_manda_o_de_nota_maior(monkeypatch, ciclo):
    monkeypatch.setattr(mercadolivre, "cliente_padrao", lambda: object())
    monkeypatch.setattr(ml_geral, "da_vez", lambda g, c: [("A", "Óculos"), ("B", "Escovas")])
    rankings = {"A": [REAIS[3]], "B": [REAIS[0]]}
    monkeypatch.setattr(ml_geral, "mais_vendidos", lambda cid, c: rankings[cid])
    monkeypatch.setattr(ml_geral, "catalogo", lambda termo, c, limite=10: [])
    monkeypatch.setattr(ml_geral, "em_alta_da_vez", lambda g, c: (_ for _ in ()).throw(AssertionError("em alta")))
    pipeline.executar_ciclo(ciclo, [Grupo("clube", "Clube", ofertas_gerais=True, desconto_minimo=25,
                                          preco_minimo=25)], registrar=False)
    assert ciclo.envios[-1] == "1"  # a Mondial, não o óculos que veio primeiro


def test_estoque_vazio_nao_aparece_no_log(monkeypatch, ciclo, caplog):
    import logging
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(mercadolivre, "cliente_padrao", lambda: object())
    monkeypatch.setattr(ml_geral, "da_vez", lambda g, c: [])
    monkeypatch.setattr(ml_geral, "em_alta_da_vez", lambda g, c: [])
    pipeline.executar_ciclo(ciclo, [Grupo("clube", "Clube", ofertas_gerais=True)], registrar=False)
    assert not any("Ofertas gerais do ML" in r.message for r in caplog.records)


def test_painel_pisos_do_grupo_e_marcas(arquivos):
    import yaml
    d = painel.ler_tudo()
    d["env"] = {}
    g = d["grupos"][0]
    assert g["desconto_minimo"] is None and g["preco_minimo"] is None  # grupo comum: vale o geral
    g["desconto_minimo"], g["preco_minimo"] = 30, 49.9
    d["filtros"]["marcas_boas"] = ["Saint Germain"]
    assert painel.salvar(d) == []
    y = yaml.safe_load((arquivos / "config.yaml").read_text(encoding="utf-8"))
    gy = y["grupos"][g["chave"]]
    assert gy["desconto_minimo"] == 30 and gy["preco_minimo"] == 49.9
    assert y["filtros"]["marcas_boas"] == ["Saint Germain"]
    d = painel.ler_tudo()
    d["env"] = {}
    d["grupos"][0]["desconto_minimo"] = None  # apagar = volta ao geral
    assert painel.salvar(d) == []
    assert "desconto_minimo" not in yaml.safe_load((arquivos / "config.yaml").read_text(encoding="utf-8"))["grupos"][g["chave"]]


def test_painel_grupo_de_ofertas_gerais_mostra_os_pisos_padrao(arquivos):
    d = painel.ler_tudo()
    d["env"] = {}
    d["grupos"][0]["ofertas_gerais"] = True
    import yaml
    assert painel.salvar(d) == []
    d = painel.ler_tudo()
    assert (d["grupos"][0]["desconto_minimo"], d["grupos"][0]["preco_minimo"]) == (25, 25)
    gy = yaml.safe_load((arquivos / "config.yaml").read_text(encoding="utf-8"))["grupos"][d["grupos"][0]["chave"]]
    assert "desconto_minimo" not in gy and "preco_minimo" not in gy  # padrão: não precisa escrever


def test_painel_valida_os_pisos(arquivos):
    d = painel.ler_tudo()
    d["env"] = {}
    d["grupos"][0]["desconto_minimo"] = 150
    d["grupos"][0]["preco_minimo"] = -1
    erros = painel.salvar(d)
    assert any("desconto mínimo do grupo" in e for e in erros) and any("preço mínimo do grupo" in e for e in erros)


def test_teste_h_mostra_o_que_seria_mandado_e_o_que_foi_cortado(monkeypatch, tmp_path):
    from ofertas import teste_fontes
    g = Grupo("clube", "Clube", {"MLB23332": "Tênis", "MLB1": "Limpeza Automotiva"}, ofertas_gerais=True,
              desconto_minimo=25, preco_minimo=25)
    monkeypatch.setattr(config, "grupos", [g])
    monkeypatch.setattr(config, "palavras_bloqueadas", ["masculino"])
    monkeypatch.setattr(mercadolivre, "cliente_padrao", lambda: object())
    pedidos = []
    monkeypatch.setattr(ml_geral, "mais_vendidos", lambda cid, c: pedidos.append(cid) or [
        _o("A", "Tênis Nike Revolution 7 Masculino", 199.9, 399.9, 1),
        _o("B", "Tênis Olympikus Corre 3 Feminino", 229.9, 399.9, 2),
        _o("C", "Tênis Casual Básico Feminino", 59.9, 119.9, 3)])
    teste_fontes._linhas.clear()
    assert teste_fontes._h_moda()
    texto = "\n".join(teste_fontes._linhas)
    assert pedidos == ["MLB23332"]  # só a categoria de moda do grupo
    assert "1 palavra bloqueada" in texto and "masculino (1)" in texto
    assert texto.index("Olympikus") < texto.index("Tênis Casual")  # marca na frente
