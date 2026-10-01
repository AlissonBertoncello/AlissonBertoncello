import socket

import pytest

from ofertas import main


def _porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_segundo_bot_e_recusado(capsys):
    porta = _porta_livre()
    primeiro = main.travar_instancia(porta)
    try:
        with pytest.raises(SystemExit) as e:
            main.travar_instancia(porta)
        assert e.value.code == main.JA_RODANDO
        assert "já está rodando" in capsys.readouterr().out
    finally:
        primeiro.close()


def test_trava_liberada_quando_o_bot_fecha():
    porta = _porta_livre()
    main.travar_instancia(porta).close()
    main.travar_instancia(porta).close()  # não levanta: a porta foi liberada
