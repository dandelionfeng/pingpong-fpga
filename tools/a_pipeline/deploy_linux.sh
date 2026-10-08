#!/usr/bin/env bash
# Local staging only. Explicitly run on the target to install/use it.
set -euo pipefail
if [[ $# -ne 2 ]]; then echo "Usage: deploy_linux.sh BUILD_DIRECTORY STAGING_DIRECTORY" >&2;exit 2;fi
taskBuild=$(realpath "$1")
taskStage=$(realpath -m "$2")
if [[ -e "$taskStage/bin/pipeline_cli" ]]; then echo 'Choose a fresh staging directory' >&2;exit 2;fi
cmake --install "$taskBuild" --prefix "$taskStage"
mkdir -p "$taskStage/config" "$taskStage/lib"
taskDependencies="${A_PIPELINE_DEPS:-$HOME/.local/share/afh03-a-pipeline}"
for taskLibrary in core imgproc imgcodecs; do
  cp -a "$taskDependencies/opencv/lib/libopencv_$taskLibrary.so"* "$taskStage/lib/"
done
if [[ -e "$taskStage/bin/pipeline_gui" ]]; then
  taskQt="$taskDependencies/qt/6.8.3/gcc_64"
  for taskLibrary in Core Gui Widgets OpenGL Test DBus XcbQpa; do
    cp -a "$taskQt/lib/libQt6$taskLibrary.so"* "$taskStage/lib/"
  done
  cp -a "$taskQt/lib/libicu"*.so* "$taskStage/lib/"
  cp -a "$taskQt/plugins" "$taskStage/"
fi
taskSource=$(cd "$(dirname "$0")/../.." && pwd)
cp "$taskSource/software/pc_pipeline/configs/v4l2.json" "$taskStage/config/"
file "$taskStage/bin/pipeline_cli" > "$taskStage/binary-architecture.txt"
export LD_LIBRARY_PATH="$taskStage/lib:${LD_LIBRARY_PATH:-}"
ldd "$taskStage/bin/pipeline_cli" > "$taskStage/runtime-dependencies.txt" || true
if [[ -e "$taskStage/bin/pipeline_gui" ]]; then ldd "$taskStage/bin/pipeline_gui" >> "$taskStage/runtime-dependencies.txt";fi
if grep -q 'not found' "$taskStage/runtime-dependencies.txt"; then echo 'Missing runtime libraries; see runtime-dependencies.txt' >&2;exit 1;fi
printf 'Local staging ready: %s\n' "$taskStage"
cat > "$taskStage/run-cli.sh" <<'LAUNCH'
#!/usr/bin/env bash
set -euo pipefail
taskStage=$(cd "$(dirname "$0")" && pwd)
export LD_LIBRARY_PATH="$taskStage/lib:${LD_LIBRARY_PATH:-}"
exec "$taskStage/bin/pipeline_cli" "$@"
LAUNCH
cat > "$taskStage/run-gui.sh" <<'LAUNCH'
#!/usr/bin/env bash
set -euo pipefail
taskStage=$(cd "$(dirname "$0")" && pwd)
export LD_LIBRARY_PATH="$taskStage/lib:${LD_LIBRARY_PATH:-}"
export QT_PLUGIN_PATH="$taskStage/plugins"
exec "$taskStage/bin/pipeline_gui" "$@"
LAUNCH
chmod +x "$taskStage/run-cli.sh" "$taskStage/run-gui.sh"
