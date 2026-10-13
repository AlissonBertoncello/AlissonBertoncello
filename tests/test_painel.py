import json
import shutil
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from ofertas import config as cfg
from ofertas import painel

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def arquivos(tmp_path, monkeypatch):
    shutil.copy(RAIZ / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / ".env").write_text("# segredos\nML_CLIENT_ID=123\nML_CLIENT_SECRET=segredo\nOUTRA=x\n",
                                   encoding="utf-8")
    monkeypatch.setattr(painel, "ARQ_CONFIG", tmp_path / "config.yaml")
    monkeypatch.setattr(painel, "ARQ_ENV", tmp_path / ".env")
    monkeypatch.setattr(painel, "DATA_DIR", tmp_path)
    return tmp_path


def test_salvar_sem_mudar_nada_mantem_o_arquivo_igual(arquivos):
    antes = (arquivos / "config.yaml").read_text(encoding="utf-8")
    d = painel.ler_tudo()
    d["env"] = {}
    assert painel.salvar(d) == []
    assert (arquivos / "config.yaml").read_text(encoding="utf-8") == antes
    assert (arquivos / "config_anterior.yaml").exists()
    assert (arquivos / "meu_config.yaml").read_text(encoding="utf-8") == antes


def test_ler_tudo_nao_devolve_segredos(arquivos):
    env = painel.ler_tudo()["env"]
    assert env["ML_CLIENT_ID"] == {"secreto": False, "definido": True, "valor": "123"}
    assert env["ML_CLIENT_SECRET"] == {"secreto": True, "definido": True, "valor": ""}
    assert env["SHOPEE_APP_SECRET"]["definido"] is False


def test_salvar_mudancas_mantendo_comentarios(arquivos):
    d = painel.ler_tudo()
    d["geral"]["intervalo_minutos"] = 10
    fit = next(g for g in d["grupos"] if g["chave"] == "fitness")
    fit["ativo"] = True
    fit["whatsapp"].append("Fitness 2")
    fit["convite"] = "https://chat.whatsapp.com/ABC"
    d["grupos"].append({"chave": "casa", "ativo": True, "nome": "Casa 🏠", "whatsapp": ["Casa"], "convite": "",
                        "categorias": [{"id": "MLB1574", "nome": "Casa"}], "shopee": ["panela"], "bloquear": ["pet"]})
    d["env"] = {"ML_ETIQUETA": "minha_tag"}
    assert painel.salvar(d) == []
    texto = (arquivos / "config.yaml").read_text(encoding="utf-8")
    assert "  intervalo_minutos: 10        # de quanto em quanto tempo" in texto  # comentário mantido
    grupos = {g.chave: g for g in cfg.ler_grupos(yaml.safe_load(texto)["grupos"])}
    assert grupos["fitness"].whatsapp == ["Achadinhos Fitness 💪", "Fitness 2"]
    assert grupos["casa"].bloquear == ["pet"] and grupos["casa"].categorias == {"MLB1574": "Casa"}
    env = (arquivos / ".env").read_text(encoding="utf-8")
    assert "ML_CLIENT_SECRET=segredo" in env and "# segredos" in env and "ML_ETIQUETA=minha_tag" in env


def test_desligar_e_excluir_grupo(arquivos):
    d = painel.ler_tudo()
    d["env"] = {}
    d["grupos"] = [g for g in d["grupos"] if g["chave"] != "fitness"]
    next(g for g in d["grupos"] if g["chave"] == "bebe")["ativo"] = False
    assert painel.salvar(d) == []
    y = yaml.safe_load((arquivos / "config.yaml").read_text(encoding="utf-8"))
    assert "fitness" not in y["grupos"]
    assert y["grupos"]["bebe"]["ativo"] is False
    assert [g.chave for g in cfg.ler_grupos(y["grupos"])] == ["mulher"]


def test_validacao(arquivos):
    d = painel.ler_tudo()
    d["env"] = {}
    d["geral"]["intervalo_minutos"] = 0
    d["geral"]["horario_ativo"] = "8h-23h"
    d["grupos"].append({"chave": "Novo Grupo", "ativo": True, "nome": "X", "whatsapp": [], "convite": "chat",
                        "categorias": [{"id": "abc", "nome": "?"}], "shopee": [], "bloquear": []})
    erros = " | ".join(painel.validar(d))
    for trecho in ("intervalo_minutos", "horário ativo", "código interno", "categoria 'abc'",
                   "nome do grupo no WhatsApp", "convite precisa"):
        assert trecho in erros
    antes = (arquivos / "config.yaml").read_text(encoding="utf-8")
    assert painel.salvar(d)
    assert (arquivos / "config.yaml").read_text(encoding="utf-8") == antes  # nada gravado


def test_env_so_aceita_texto_de_uma_linha(arquivos):
    d = painel.ler_tudo()  # "env" aqui vem com as informações da tela, não com valores
    assert any("ML_CLIENT_ID" in e for e in painel.validar(d))
    d["env"] = {"ML_ETIQUETA": "a\nML_CLIENT_SECRET=hack"}
    assert any("ML_ETIQUETA" in e for e in painel.validar(d))


def test_config_ignora_grupo_desligado():
    assert [g.chave for g in cfg.ler_grupos({
        "a": {"categorias": ["MLB1"]}, "b": {"ativo": False, "categorias": ["MLB1"]}})] == ["a"]


@pytest.fixture
def servidor(arquivos):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), painel._Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _req(url, dados=None, cabecalhos=None):
    r = urllib.request.Request(url, data=json.dumps(dados).encode() if dados is not None else None,
                               headers=cabecalhos or {})
    try:
        with urllib.request.urlopen(r) as resp:
            corpo = resp.read()
            return resp.status, json.loads(corpo) if "/api/" in url else corpo
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_servidor_pagina_e_api(servidor):
    status, html = _req(servidor + "/")
    assert status == 200 and b"Painel do Bot de Ofertas" in html
    status, d = _req(servidor + "/api/config")
    assert status == 200 and {g["chave"] for g in d["grupos"]} >= {"mulher", "bebe"}


def test_servidor_exige_cabecalho_para_salvar(servidor):
    _, d = _req(servidor + "/api/config")
    d["env"] = {}
    assert _req(servidor + "/api/config", d)[0] == 403  # sem X-Painel (ex: outro site)
    status, r = _req(servidor + "/api/config", d, {"X-Painel": "1", "Content-Type": "application/json"})
    assert status == 200 and r["ok"] is True


def test_servidor_recusa_outro_host(servidor):
    assert _req(servidor + "/api/config", cabecalhos={"Host": "site-malicioso.com"})[0] == 403


# ── o bot em execução aplica a configuração nova ──────────────────────────────

class _Destino:
    nome = "whatsapp"

    def __init__(self, falha=None):
        self.falha = falha
        self.preparados = []

    def preparar(self, grupos):
        if self.falha:
            raise RuntimeError(self.falha)
        self.preparados.append([g.chave for g in grupos])


def test_bot_aplica_grupos_novos(monkeypatch):
    import argparse
    import logging

    from ofertas import main
    from ofertas.models import Grupo
    novos = [Grupo("a", "A", {"MLB1": "x"}, whatsapp=["A"])]
    monkeypatch.setattr(cfg, "recarregar", lambda: None)
    monkeypatch.setattr(cfg.config, "grupos", novos)
    destino = _Destino()
    grupos, d = main._recarregar(argparse.Namespace(grupo=None), ["antigos"], destino, logging.getLogger())
    assert grupos == novos and destino.preparados == [["a"]]


def test_bot_segue_com_grupos_antigos_se_o_novo_falhar(monkeypatch):
    import argparse
    import logging

    from ofertas import main
    from ofertas.models import Grupo
    monkeypatch.setattr(cfg, "recarregar", lambda: None)
    monkeypatch.setattr(cfg.config, "grupos", [Grupo("a", "A", {"MLB1": "x"}, whatsapp=["Não existe"])])
    destino = _Destino(falha="Grupo 'Não existe' não encontrado")
    grupos, _ = main._recarregar(argparse.Namespace(grupo=None), ["antigos"], destino, logging.getLogger())
    assert grupos == ["antigos"]
