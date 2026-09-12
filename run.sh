#!/usr/bin/env bash
# ==============================================================================
# fut-bin - Melhores Momentos (Pelada)
# Cria/ativa o ambiente virtual e roda um dos scripts do pipeline.
# ==============================================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "🔧 Criando ambiente virtual em .venv ..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip -q
    "$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" -q
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "⚠ ffmpeg não encontrado no PATH. Instale-o (ex.: sudo apt install ffmpeg) antes de continuar." >&2
fi

usage() {
    cat <<EOF
Uso: ./run.sh <comando> [opções do script]

Comandos (ver README.md para o fluxo completo):
  site               Assistente completo no navegador (passo a passo, sem rodar nada na mão)
  tray               Inicia o servidor e coloca o ícone na bandeja do sistema
  stop               Para os servidores e a bandeja do sistema com segurança
  status             Exibe status, PIDs e uso de memória em tempo real
  folha_placar       Corte manual - folhas de contato do placar / conversão de horários -> gols.json
  detectar_gols      Corte manual - corta os clipes de gol (ou detecção automática do placar)
  montar_video       Corte manual - monta o vídeo final a partir de partida.json
  diagnosticar       Conferência da região/estabilidade do placar
  marcador           Abre o marcador.html isolado (sem servidor) no navegador padrão
  shell              Só ativa o ambiente virtual num subshell (sem rodar nada)

Exemplos:
  ./run.sh tray                          # recomendado: servidor com ícone na bandeja do sistema
  ./run.sh site                          # assistente com todos os passos no navegador
  ./run.sh stop                          # para o servidor e fecha a bandeja
  ./run.sh status                        # confere PIDs e uso de memória
  ./run.sh site --port 8000
  ./run.sh folha_placar --source_video_path pelada.mp4 --fim 58:23 --intervalo 10
  ./run.sh detectar_gols --source_video_path pelada.mp4 --cortar --output_dir gols
  ./run.sh montar_video --partida partida.json --clipes gols/clipes
  ./run.sh marcador
EOF
}

cmd="${1:-}"
[ $# -gt 0 ] && shift || true

case "$cmd" in
    tray)
        if [ -x "$HOME/.local/bin/fut-bin" ]; then
            exec "$HOME/.local/bin/fut-bin" start "$@"
        else
            exec python "$SCRIPT_DIR/tray.py" start "$@"
        fi
        ;;
    stop)
        if [ -x "$HOME/.local/bin/fut-bin" ]; then
            exec "$HOME/.local/bin/fut-bin" stop "$@"
        else
            exec python "$SCRIPT_DIR/tray.py" stop "$@"
        fi
        ;;
    status)
        if [ -x "$HOME/.local/bin/fut-bin" ]; then
            exec "$HOME/.local/bin/fut-bin" status "$@"
        else
            exec python "$SCRIPT_DIR/tray.py" status "$@"
        fi
        ;;
    site)
        host="127.0.0.1"; port="8000"
        # extrai --host/--port dos args (se vierem) só pra montar a URL do xdg-open;
        # os mesmos args continuam sendo repassados pro assistente_web.py abaixo
        args=("$@")
        for i in "${!args[@]}"; do
            case "${args[$i]}" in
                --host) host="${args[$((i+1))]}" ;;
                --port) port="${args[$((i+1))]}" ;;
            esac
        done
        if command -v xdg-open >/dev/null 2>&1; then
            ( sleep 1.5 && xdg-open "http://$host:$port" >/dev/null 2>&1 & )
        elif command -v open >/dev/null 2>&1; then
            ( sleep 1.5 && open "http://$host:$port" & )
        fi
        exec python "$SCRIPT_DIR/assistente_web.py" "$@"
        ;;
    folha_placar)
        exec python "$SCRIPT_DIR/folha_placar.py" "$@"
        ;;
    detectar_gols)
        exec python "$SCRIPT_DIR/detectar_gols.py" "$@"
        ;;
    montar_video)
        exec python "$SCRIPT_DIR/montar_video.py" "$@"
        ;;
    diagnosticar)
        exec python "$SCRIPT_DIR/diagnosticar_placar.py" "$@"
        ;;
    marcador)
        marcador_path="$SCRIPT_DIR/marcador.html"
        if command -v xdg-open >/dev/null 2>&1; then
            xdg-open "$marcador_path" >/dev/null 2>&1 &
        elif command -v open >/dev/null 2>&1; then
            open "$marcador_path"
        else
            echo "Abra manualmente no navegador: $marcador_path"
        fi
        ;;
    shell)
        exec "$SHELL"
        ;;
    ""|-h|--help|help)
        usage
        ;;
    *)
        echo "❌ Comando desconhecido: $cmd" >&2
        echo >&2
        usage >&2
        exit 1
        ;;
esac
