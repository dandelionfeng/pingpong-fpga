# 本地历史资料定位

2026-10-08按蒲公英要求，把旧路线、旧分工、旧TD实验及被替代的文档核查/交接从当前GitHub文件树移出。这里仅保留定位页，现行工作从[当前方案](../plans/current/README.md)和[仓库首页](../README.md)开始。

本机保存位置：`C:\FPGA competition-backups\20261008-repo-cleanup`。

- `files/`：按原仓库路径保存原始工作区字节。
- `git-bytes/`：按同样路径保存清理基准提交的Git blob字节；行尾差异分别记录。
- `manifest.json`：每个文件的原路径、动作、字节数、SHA-256、来源提交与Git blob；所有备份核验后才移出文件。
- `repository-before-cleanup.bundle`：清理前全部本地Git引用的完整备份，已执行`git bundle verify`。

共享的[定位与校验清单](../data/manifests/local-history-20261008.json)保留在仓库。恢复单个文件时，先在清单中查`source_path`，从本机`files/<source_path>`复制到独立目录，核对`sha256`。需要原Git字节时使用`git-bytes/<source_path>`及`git_sha256`。不要在现行目录直接覆盖同名实现。

旧PH1A180 TD工具测试、PH1A90灰度/去噪/亮度/ROI实验、H10/RK3566/UDP、SC130GS/MIPI、旧100°镜头路线均属历史资料。复用某个模块须明确选入新任务目录并重新验证。现行A前三段及B后四段参考RTL未移出。

本机原`C:\FPGA competition\archive\local-debug\v2026-10-05_td_experiments`仍保存被忽略的生成工程、日志和波形，本轮未删除。厂商资料、真实素材、权重、`.tools`及运行包也未删除。Git历史保留，清理作用于当前文件树，未重写远端历史。
