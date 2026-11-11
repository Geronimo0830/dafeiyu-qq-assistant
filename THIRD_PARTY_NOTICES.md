# 第三方组件与许可说明

## 项目署名

产品：大肥鱼 QQ 助手。项目作者与维护者：Xean。

当前版本采用海洋蓝界面，提供安装向导与本地控制台，包含角色设置、语音费用确认及后台凭证显示控制等功能。

## 项目许可

Xean 持有权利的部分采用根目录 `LICENSE` 中的 PolyForm Noncommercial 1.0.0，必须保留的声明见 `NOTICE`。第三方组件与素材不适用本项目新增的非商业限制，保留各自的许可和权利归属。

## 第三方组件

- AstrBot 4.29.3：https://github.com/AstrBotDevs/AstrBot，AGPL-3.0，随附许可证见实际安装目录 `program/astrbot/LICENSE`；该组件及对应源码保持原许可。
- NapCat v4.18.41：https://github.com/NapNeko/NapCatQQ，其 Limited Redistribution License 限定再分发与使用范围；保留原版程序、版权、来源及完整许可，具体以该版本随附许可证为准。
- dafeiyu-config-pack：https://github.com/zexuanw958-svg/dafeiyu-config-pack，MIT，许可位于 `vendor/dafeiyu-config-pack/LICENSE`，安装后位于 `program/pack/LICENSE` 和 `userdata/pack/LICENSE`。
- Python 3.12.10：保留嵌入式运行时随附的完整 `LICENSE.txt`；另在 `program/licenses/Python-3.12.10-LICENSE.txt` 提供副本。
- NapCat 包附带的 Node.js v22.11.0：完整版本许可及依赖声明位于 `program/licenses/Node-v22.11.0-LICENSE.txt`。
- 打包使用 reduced `7zr.exe` 与 LZMA SDK 25.01 的 `7zSD.sfx`。这些 SDK 组件的公有领域说明与来源记录位于 `program/licenses/`，启动包的 `licenses/` 中也有副本；本说明不将完整 7-Zip 产品的许可与这些组件混为一谈。
- 各 AstrBot 插件、语音模型及 Python/Node 运行依赖保留各自许可和署名。来源材料见 `build/licenses/`；安装后见 `program/licenses/`。

NapCat 官方发行包中的客户端库及其他二进制组件仍受各自权利约束，不能仅凭 NapCat 自身许可认定全部随附组件均已获公开再分发授权。当前许可材料不等于对所有依赖的完整法律审核。

本项目调整了配置包中的默认角色文案、音色描述以及语音/唱歌插件的默认音色字符串；插件元数据中的作者仍是原作者。这不表示第三方插件由 Xean 原创。

## 图片与图标

- 首页人物图由用户提供，其处理版位于 `app/web/img/dafeiyu-welcome-clean.png`。图片经 AI 去水印处理，部分线条有变化。去水印不改变原图权利归属。
- 蓝色双波纹图标由本项目以矢量/绘图代码制作，源文件为 `app/web/img/brand.svg`。
- 表情包及其他第三方素材的版权与使用范围由各权利人决定，不因本项目代码许可改变。公开分发前需确认相应素材的再分发权限。
- 发布 EXE 不内置 `blue-fat-fish-meme-pack` 和 `deepseek-fanart-meme-pack` 的图片，安装时从上游获取。这两套素材的上游说明未提供原素材许可；相关声明分别见 https://github.com/anka-afk/blue-fat-fish-meme-pack/blob/v1.0.0/LICENSE 和 https://github.com/anka-afk/deepseek-fanart-meme-pack/blob/v1.0.0/LICENSE。
