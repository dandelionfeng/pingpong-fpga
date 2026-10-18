# 100DOH teacher 验证 —— 阻塞报告

日期：2026-10-15　分支：`codex/c-pc-detector`

## 结论

**100DOH teacher 无法获取，因此无法在 BNDSTT_MANUAL_GT_V1 的 54 个 hand GT 上给出
P / R / F1 / AP50。本任务在下载阶段即被阻塞，没有任何训练或评测被执行。**

按你的第 6 条要求精神，同样处理：**立即停止这条路线**，等待你决定是否转人工标注。

---

## 官方来源（已核实）

| 项 | 值 |
| --- | --- |
| 项目页 | https://fouheylab.eecs.umich.edu/~dandans/projects/100DOH/ |
| 下载页 | https://fouheylab.eecs.umich.edu/~dandans/projects/100DOH/download.html |
| 代码仓库 | https://github.com/ddshan/hand_detector.d2 （detectron2） |
| 论文 | Shan, Geng, Shu, Fouhey, *Understanding Human Hands in Contact at Internet Scale*, CVPR 2020 |
| 模型 | **Faster-RCNN X101-FPN**，100K 上 Box AP **90.32%**；100K+ego 上 **90.46%** |
| 数据规模 | 99,899 帧 / **189,426 个 hand box** |
| 许可 | 页面声明 **non-commercial research purposes only**；数据需同意 agreement |

**你要的 100K 与 100K+ego 两个 hand detector 就是上表这两个 Google Drive 文件。**

---

## 阻塞原因（两条，均已复现）

### 1. 权重文件在 Google Drive 上已不可获取

官方 README 给出的两个 file ID：

- 100K：`1o6-zmZTehpLozAOibm2uqUu--WIKh88R`
- 100K+ego：`1OqgexNM52uxsPG3i8GuodDOJAGFsYkPg`

实测结果：

| 获取方式 | 结果 |
| --- | --- |
| `gdown`（标准方式） | `FileURLRetrievalError`：**"You may need to change the permission to 'Anyone with the link', or have had many accesses"** → **配额用尽 / 权限变更** |
| `https://drive.google.com/uc?export=download&id=<id>` | **HTTP 404** |
| `https://drive.usercontent.google.com/download?id=<id>&export=download` | **HTTP 404** |
| `https://docs.google.com/uc?export=download&id=<id>` | **HTTP 404** |
| `https://drive.google.com/file/d/<id>/view` | **HTTP 404** |

`gdown` 的报错信息是判断依据：**"many accesses"** 说明该文件被下载次数过多、Google 已限流，
随后端点统一返回 404。这不是本机网络问题 —— 同一台机器上 `drive.google.com` 与
`www.google.com` 均返回 200。

### 2. detectron2 无法安装（100DOH 是 d2 模型）

| 尝试 | 结果 |
| --- | --- |
| `pip install detectron2` | **PyPI 上不存在该包**（`No matching distribution found`） |
| `pip install git+https://github.com/facebookresearch/detectron2.git` | **`git clone` 失败**：`Failed to connect to github.com:443 after 21080 ms` |
| 清华 git 镜像 | 404 |
| gitee 镜像 | 405 |
| gitclone.com | 502 |
| hub.fastgit.xyz | 连接超时（HTTPS 探测返回 200，但 `git clone` 失败） |

本机现状：Python 3.12.14 + torch 2.5.1+cu121 + CUDA 12.1 + MSVC 2022 可用。
**即便源码能拿到，Python 3.12 / torch 2.5 对 detectron2 也偏新，Windows 上从源码编译
成功率本身不高。**

> 说明：`raw.githubusercontent.com` 在本机**可访问**（本报告的所有元数据都是通过它核实的），
> 受限的是 `github.com:443` 的 git 协议与 Google Drive 的文件下载端点。

---

## 没有做的事（严格按要求）

- ❌ 没有训练任何新模型
- ❌ 没有跑 TV-Hand 训练（已按你要求暂停）
- ❌ 没有做 pseudo-label
- ❌ 没有用 wrist 造任何 bbox
- ❌ 没有给出任何编造的 P / R / F1 / AP50

## 已完成且可复用的准备

- 评测脚本已就绪，**一旦拿到 teacher 权重即可直接跑**：
  `tmp/eval_hand_domain.py`（整图评测，BNDSTT_MANUAL_GT_V1，54 box）
  `tmp/eval_hand_tiled.py`（整图 + 切片两种推理对比）
- pose wrist 可行性已实测：**41/41** 帧找到手腕，**40/41** 帧手腕距真实 hand 中心
  ≤1.5 倍框对角线（中位 20 px）→ **wrist 验框方案在数据上成立**，只差可用的 teacher。
- 防泄漏 session 清单已固定（5 个），pseudo-label 阶段可直接排除。

---

## 需要你决定

1. **换一个 teacher 权重来源**：如果你们能提供 100DOH 权重的网盘镜像/学校镜像/已下载副本，
   我可以立刻跑完整评测（脚本已就绪）。
2. **换一个可获取的 teacher**：例如 TV-Hand/ContactHands 上训练的检测器（但这两个数据集的
   许可证同样未明确，且需要先训练，违反你「先不训练」的要求）。
3. **接受人工标注**：按调研建议，200–300 张真实乒乓球画面的 hand 框是唯一可靠路径。
   但你说过不要人工标数据，所以我**没有**启动，需要你明确解除该限制。
4. **接受当前接口现状**：hand 在乒乓球域不出框（baseline R=0.0000 / AP50=0.0000），
   先交付 V2.1（ball 与 racket 正常），hand 留作下一阶段。

**我停在这里，不做其他实验。**
