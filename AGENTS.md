# AGENTS.md

面向 AI Agent 的项目说明。修改本仓库前请先读这一页。

## 项目是什么

`Note` 是**个人计算机知识库**，同一份 Markdown 有两种使用形态：

1. **docsify 站点**：根目录 `index.html` 是站点入口与全部配置，`README.md` 是首页，内容全部在 `docs/`，通过 GitHub Pages 发布（仓库 `Robinpig/Note`，`.nojekyll` 保证下划线目录不被 Jekyll 吞掉）。
2. **Obsidian vault**：本机通常存在 `.obsidian/`（**不入库**，别的机器上可能没有），日常用 Obsidian 编辑，靠双向链接导航。

因此有两条硬约束：**文件名与目录名就是笔记标识**（重命名/移动会同时打断 Obsidian 双链和 docsify 绝对路径链接）；**笔记必须同时满足 docsify 渲染和 Obsidian 阅读**。

规模：`docs/` 下约千篇 Markdown，七大领域，`CS/` 是绝对主体。

**不要在文档里写任何文件总数或目录篇数**：`README.md`、`docs/CS/CS.md`、本文件一律不标注篇数，新增/删除笔记不需要回头改数字。需要精确值时现场跑脚本（见「统计各目录篇数」）。

## 环境约定（跨机器 / 跨 IDE / 跨系统）

本仓库会在**多台机器、多个 IDE Agent** 下被读取，所以本文件**刻意不绑定操作系统、绝对路径、也不绑定某台机器的现状**。读到下面内容时按这几条解读：

- **命令一律写成 POSIX shell**（macOS / Linux 直接可用）。Windows 下用 Git Bash / WSL 执行，或自行改写成等价命令；**不要把本文件里的命令当成"只在我这台机器上验证过的脚本"**。
- **`python3` 是"仓库约定的 Python 解释器"的写法**，不是硬性要求：Windows 上通常是 `python` 或 `py -3`，按本机情况替换即可。`scripts/kb-check.sh` 支持用 `PY=` / `NODE=` 覆盖解释器。
- **只用相对路径**，一律相对**仓库根目录**；不要假定仓库被克隆到哪里，也不要写死任何用户目录。
- **不要假定本机存在任何东西**（内核源码树、缓存、已装工具、上一次会话的产物）：需要时先 `ls` 确认，不存在就走远程端点、或按语义手工核对。
- **不要假定任何 IDE 专有目录存在**：`.claude/`、`.cursor/`、`.vscode/`、`.obsidian/`、`.workbuddy/` 都只是**本机工具目录且不入版本控制**（见 `.gitignore`）；本仓库的校验脚本**已随仓库入库在 `scripts/`**，不要依赖任何本机目录。**本文件是所有 Agent 的唯一说明来源**，不要另建 IDE 专有指令文件（`CLAUDE.md`、`.cursorrules`、`copilot-instructions.md` 之类）来各写一份。
- **凡是带"实测"字样的结论都带环境前提**（网络可达性、源码版本、工具行为）：换机器或换网络需重测。当"某台机器上一次成立"读，不要当永久事实。
- 本文件里**不记任何会随内容变化的快照数字**（篇数、平均链入、孤立页数）——需要时现场跑脚本。

## 目录地图

```
Note/
├── index.html          docsify 入口 + 全站配置（插件、主题、首页 CSS）
├── README.md           站点首页（同时也是 GitHub 仓库首页）—— 只做总入口：学习路径 + 各大领域入口
├── AGENTS.md           本文件
├── scripts/            质量门禁脚本（`kb-check.sh` + 校验工具，**随仓库入库**，见「校验工具」）
├── .github/workflows/  CI 定义（已入库，调用 `scripts/` 下的同一批脚本）
├── .workbuddy/         本机目录：仅 Agent 记忆（**不入库**，换机器可能没有）
├── docs/               全部笔记内容
│   ├── CS/             CS 主体
│   ├── Mathematics/    分支学科枢纽页 + 各分支
│   ├── Medicine/       医学与护理学：学科框架为主，见下节
│   ├── Psychology/     分支学科枢纽页 + 各分支
│   ├── Philosophy/
│   ├── Economics/
│   └── Sports/         运动生理学与训练应用，含三个专题子树（见下文三节「……的组织」）；Philosophy/Economics 为少量读书摘录
├── out/                IDE 编译产物副本 —— 只读，不要改（本机、不入库）
├── src/                忽略，不要改
└── wiki/、knowledge-base/、outputs/   空占位，不要改
```

仓库根另有几个**与知识库正文无关的散落文件**（`电源管理-v7.2-事实清单.md`、`.verify-v7.2-btrfs-fuse.md` 是写作期的事实核实清单；`k3cfg.json` 疑似误提交，与本库无关）——**不要把它们当笔记读，也不要据此推断目录结构**。

`docs/CS/` 下按主题分目录（另有 `img/` 存放配图，不算笔记）。主要子树与入口：

| 领域       | 目录                | 入口与说明                                                                                          |
| :------- | :---------------- | :--------------------------------------------------------------------------------------------- |
| 操作系统     | `CS/OS/`          | [OS.md](/docs/CS/OS/OS.md)；下辖 `Linux/`、`unix/`、`Windows/`、`mac/`、`Android/`、`xv6/`、`Fuchsia/`、`Book/`、`Boot/`（仅 `Grub.md`） |
| Linux 内核 | `CS/OS/Linux/`    | [Linux.md](/docs/CS/OS/Linux/Linux.md) 是该子树的**唯一枢纽**，见下节                                   |
| 框架与中间件   | `CS/Framework/`   | 总入口 [Framework/README.md](/docs/CS/Framework/README.md)（按 Java 体系 / 协调与服务注册 / 服务治理 / 网络与 RPC / 网格与网关 / 计算与数据 / 响应式 / 跨语言与 AI 分层）；**无 `Framework.md`**，具体机制仍在各框架子目录 |
| Java     | `CS/Java/`        | 语言入口与目录地图 [Java.md](/docs/CS/Java/Java.md)；JDK 与 JVM 内部机制的枢纽仍是 [JDK/JDK.md](/docs/CS/Java/JDK/JDK.md) |
| 数据库      | `CS/DB/`          | [DB.md](/docs/CS/DB/DB.md)                                                                     |
| 算法       | `CS/Algorithms/`  | [Algorithms.md](/docs/CS/Algorithms/Algorithms.md)                                             |
| 分布式      | `CS/Distributed/` | [Distributed.md](/docs/CS/Distributed/Distributed.md)                                          |
| 计算机网络    | `CS/CN/`          | [CN.md](/docs/CS/CN/CN.md)                                                                     |
| 软件工程     | `CS/SE/`          | 入口 [Engineering.md](/docs/CS/SE/Engineering.md)（`SE/SE.md` 不存在）                               |
| 云原生      | `CS/Container/`   | [Container.md](/docs/CS/Container/Container.md)（`Docker/`、`k8s/`）                              |
| 人工智能     | `CS/AI/`          | [AI.md](/docs/CS/AI/AI.md)；`LLM/` 是 agent 平台专题，入口 [LLM.md](/docs/CS/AI/LLM/LLM.md)；`NLP/`      |
| 推荐系统     | `CS/RecommenderSystem/` | [RecommenderSystem.md](/docs/CS/RecommenderSystem/RecommenderSystem.md)；召回、排序、冷启动、偏差、评估、在线架构、广告（**不是 `AI/` 的子目录**） |
| 消息队列     | `CS/MQ/`          | [MQ.md](/docs/CS/MQ/MQ.md)                                                                     |
| Golang   | `CS/Go/`          | [Go.md](/docs/CS/Go/Go.md)                                                                     |
| Python   | `CS/Python/`      | 语言入口 [Python.md](/docs/CS/Python/Python.md) + 知识地图 [Python/README.md](/docs/CS/Python/README.md)；**无子目录**，运行时层三篇 `GIL.md` / `Memory.md` / `Bytecode.md` 是这一子树的骨架，工程层 `Typing.md` / `Packaging.md` / `Performance.md` |

其余较小目录：`CO/`（组成原理）、`C/`、`C++/`、`Rust/`、`Scala/`、`TypeScript/`、`Dart/`、`assembly/`、`memory/`、`Compiler/`、`BuildTool/`（入口 `BuildTools.md`）、`Tool/`（**无 Tool.md**，代表文件 `Vim.md`）、`front-end/`（**无 front-end.md**，代表文件 `Nodejs.md`）、`Browser/`、`DesignPatterns/`、`VCS/`、`log/`、`compress/`、`Cloud/`、`BigData/`、`Blockchain/`、`Security/`、`GNU/`。

`docs/CS/Flutter.md` 是**没有同名目录的孤立文件**，不要误以为存在 `CS/Flutter/`。

跨领域索引页：`docs/CS/CS.md`（CS 总纲 + 全部主题目录清单）、`docs/CS/term.md`（术语表）、`docs/CS/Languages.md`（语言横向对比）。各目录下的 `README.md` 会被 docsify 当作该目录首页（如 `CS/OS/Linux/proc/README.md` 是进程知识地图）。

**首页与总纲的分工**：`README.md` 只做**总入口**（学习路径 + 各领域卡片，每个领域一张独立卡片，不合并），不放任何 CS 主题清单；`docs/CS/CS.md` 是 CS 的**唯一目录来源**（主题卡片 + 主题目录全展开 + 各学科定义）。不要在两处各写一份主题列表。

## 医学 / 护理学笔记的组织（`docs/Medicine/`）

2026-10 新增的第七领域，与 `Psychology/` 同为「分支学科枢纽页 + 各分支页」结构：

- `Medicine/Medicine.md` 是该领域**唯一总纲**；分支页为 `Basic_Medicine.md`、`Clinical_Medicine.md`、`Diagnosis.md`、`Public_Health.md`、`Medical_History_Ethics.md`。
- 护理学是**唯一有子目录**的分支：`Medicine/Nursing/` 下 `Nursing.md`（总纲）+ 11 篇分支页，按**基础层 / 场景层 / 延伸层**三层组织——基础层 `Nursing_Fundamentals.md`；场景层 `Clinical_Nursing.md`、`Maternal_Pediatric_Nursing.md`、`Psychiatric_Nursing.md`、`OR_Sterile_Supply.md`、`Emergency_Disaster_Nursing.md`、`Palliative_Care.md`、`Gerontological_Nursing.md`；延伸层 `Community_Home_Nursing.md`、`Nursing_Research_Education.md`、`Nursing_Informatics.md`；`Nursing_Management_Ethics.md` 贯穿全部。新增护理学内容一律放 `Nursing/`，不要在 `Medicine/` 根下平铺。
- **护理学已有第二个子目录**：`Nursing/Cardiovascular/`（2026-10 新增，8 篇），是**第一个「专科深化层」**——示范单个科室的疾病谱如何再展开。结构为 `Cardiovascular_Care.md`（总纲，含**三条贯穿主线：缺血与灌注 / 容量与压力 / 节律与电**）+ 7 篇疾病页（`Coronary_Heart_Disease.md`、`Heart_Failure.md`、`Arrhythmia.md`、`Hypertension.md`、`Valvular_Heart_Disease.md`、`Cardiomyopathy_Myocarditis.md`、`Pericardial_Disease.md`）。后续若深化其他科室（如呼吸科、消化科、糖尿病），**照此结构新建 `Nursing/<Specialty>/`，不要平铺进 `Nursing/`**。
- ⚠️ **医学 × CS 的固定交叉点**：`Nursing/Nursing_Informatics.md` 是本库医学与计算机科学**最直接**的交叉页（决策支持、远程护理、可穿戴、AI 辅助），链向 `CS/AI/AI.md` 与 `CS/AI/LLM/LLM.md`。写 AI 相关医学内容时**从这篇转链**，不要重复叙述 AI 原理。
- ⚠️ **内容口径：学科框架为主，谨慎写临床细节**。剂量、诊疗路径、指南推荐等级、各类指标阈值、给药方案与器械参数**不收录**——它们随指南更新而变化，写死必然过时且有出错风险。需要时只写「关注点与判断逻辑」，并在页首用 `> [!WARNING]` 块声明「不收录具体规程，以最新指南与机构规范为准」。
- ⚠️ 医学笔记用**中文术语 + 英文原名**（如「循证医学（evidence-based medicine）」首次出现时），这是本库其他领域（CS/哲学/心理学）一致的做法。
- 医学与本库其他领域的固定交叉点：`Sports/Anatomy.md`（解剖）、`Psychology/Biological_Psychology.md`（生理基础）、`Philosophy/Ethics.md`（伦理四原则的哲学源流）、`Mathematics/Probability_Statistics.md`（研究设计与统计推断）、`CS/AI/AI.md`（AI 辅助决策的算法责任）。新增医学页时优先链到这些已有页，不要重复新建。

## 科学减重专题的组织（`docs/Sports/Weight_Management/`）

2026-10 新增，本库**第一个运动学专题子树**：

- 结构为 `Weight_Management.md`（总纲，含**三条贯穿主线：缺口的三个维度 / 瘦体重是承重墙 / 维持是另一道题**）+ 5 篇机制分册：`Energy_Balance.md`、`Nutrition_Intervention.md`、`Exercise_Prescription.md`、`Assessment_and_Tracking.md`、`Behavior_and_Maintenance.md`。五页按「存得下 → 吃什么 → 怎么动 → 怎么量 → 怎么守」的因果链分工，**同一结论只有归属分册可以展开写，其它页只链接不重述**（各页开头已写明分工，新增内容先确认归属再动笔）。
- 领域枢纽是 `Sports/Sports.md`，**新增子目录后必须回它挂入口**（本库通用规则，此处同样适用）。
- ⚠️ **内容口径：机制 + 自我管理**。不收录药物、代谢手术、诊疗路径、指南推荐等级与个体化热量处方——与 `Medicine/` 口径一致，但本专题额外要求**不得写成减重操作方案**（不写「摄入须低于 X kcal」这类硬阈值、不给极端限制的执行细节），并保留「不适合自行减重」与进食障碍求助边界的小节。页首一律用 `> [!WARNING]` 块声明口径。
- ⚠️ **引用纪律高于全库平均水平**：这个题目网上伪科学极多，正文数字断言必须能指到一手文献。外部引用一律经 PubMed eutils 的 `esearch` + `esummary` 核对 PMID 与标题**逐字一致**后才写；`pubmed.ncbi.nlm.nih.gov/<PMID>/` 的 HTML 页在本机返回 **203 拦截页**，**不要用它的状态码判断链接是否有效**（eutils 返回 200 + JSON 才算）。核实不上的结论改成机制叙述，不要留数字。
- 与本库其它领域的固定交叉点：`Sports/Anatomy.md`（动作模式与肌群，运动处方页只借用其框架）、`Psychology/Biological_Psychology.md`（食欲与内分泌调控）、`Psychology/Cognitive_Bias.md` 与 `Psychology/Positive_Psychology.md`（进食行为与动机）、`Medicine/Public_Health.md`（肥胖的流行病学与三级预防）、`Mathematics/Probability_Statistics.md`（测量噪声与均值）。新增内容优先链到这些已有页，不要重复新建。

## 脊柱健康专题的组织（`docs/Sports/Spine_Health/`）

2026-10 新增，`Sports/` 的第二个专题子树，结构与 `Weight_Management/` 同为「枢纽 + 共通底座 + 分册」：

- 结构为 `Spine_Health.md`（总纲，含**三条贯穿主线：疼痛不等于病灶 / 姿势是剂量问题不是形态问题 / 康复是分级暴露不是保护**）+ 1 篇共通底座 `Posture_and_Load.md` + 3 篇病种分册 `Cervical_Spondylosis.md`、`Lumbar_Disc_Herniation.md`、`Scoliosis.md`。
- ⚠️ **底座页刻意不含任何动作清单**（颈部、腰部、侧弯同一动作的安全性互不相同，集中放置会让读者忽略它属于哪一型）。新增动作类内容一律写进对应病种页，不要回填到底座页。
- **分册按「机制差异最大的维度」切开，不按解剖位置**：颈椎页的重心是**分型**（颈型 / 神经根型 / 脊髓型 / 椎动脉型 / 交感型，其中两型禁止自行训练），腰突页的重心是**时间**（急性期几乎什么都不做才是对的，恢复期只靠负荷渐进），侧弯页的重心是**监测与决策**（生长期、由生长速度而非症状决定节奏，不能靠自觉训练解决）。加新病种前先确定它的主导维度，避免写成第四份「通用脊柱保养」。
- `Posture_and_Load.md` 的**红旗信号表**与 **24 小时判读规则**是全库健康类内容的共用件：其它页与后续运动康复类笔记**引用而不重述**。姿势建议一律写成**时间参数**（多久换一次、连续多久算过量），不写成形态目标。
- ⚠️ **内容口径：机制理解 + 自我管理方法学**，与 `Medicine/` 一致地不收录药物、牵引剂量、手术方式、诊疗路径与指南推荐等级；本专题额外声明**结构性退变不可逆，目标是功能 / 负荷耐受 / 生活质量而非把结构「治回去」**。页首一律用 `> [!WARNING]` 块声明口径并列出该页红旗症状。
- ⚠️ 中文语境的特有反模式需要专门处理（如「米字操」的传播度远高于其适用边界）：这类内容写成独立小节，说明**它适用的人群恰恰是还没有症状的人**，并给出禁忌人群清单——不要只否定不给判据。
- 引用纪律与「科学减重专题」同一条（PubMed eutils 逐字核对，见上一节）。中文政府 / 官媒健康科普页（`beijing.gov.cn`、`gmw.cn`、`kepuchina.cn`）可用作反模式与本土指南表述的来源，但机制与数据断言仍要回到一手文献。
- 固定交叉点：`Sports/Anatomy.md`（训练中的肌群调用与渐进超负荷，本专题只借用不重述）、`Medicine/Basic_Medicine.md`（结构性解剖的入口——⚠️ `Medicine/Anatomy.md` 由并行会话补写中、尚未入库，**不要挂链到它**）、`Weight_Management/`（体重与腰椎负荷的并行收益路径）。

## 关节与肌腱健康专题的组织（`docs/Sports/Joint_Health/`）

2026-10 新增，`Sports/` 的第三个专题子树，结构与前两棵同为「枢纽 + 共通底座 + 分册」，但**它是脊柱子树的平行子树，不是它的续篇**：

- 结构为 `Joint_Health.md`（总纲，含**三条贯穿主线：名字里的「-itis」不是机制 / 形态是负荷史的记录而不是判决书 / 负荷是活性成分而没有任何一种手法是金标准**）+ 1 篇共通底座 `Tendon_and_Load.md` + 4 篇部位分册 `Shoulder.md`、`Elbow_and_Wrist.md`、`Hip_and_Knee.md`、`Ankle_and_Foot.md`。
- ⚠️ **为什么不并进 `Spine_Health/`**：外周的证据结构与脊柱**相反**。脊柱那边最有用的一条是「影像与症状分离，别被片子吓到」，这句话搬到四肢会真的伤人——跟腱完全断裂、股骨头骨坏死、进行性大鱼际肌萎缩都必须靠结构与体征判断。因此底座页**必须同时**给出「形态 ≠ 症状」的流行率总表**和**「三种必须提高结构权重的例外」，只写前一半就是写坏。
- **各分册按主导维度切开，不按解剖位置平铺**：肩写**解释框架的崩塌**（撞击隐喻 + 盲法假手术试验史）、肘腕写**时间**（注射的短期获益在一年内反转）、髋膝写**分层与决策顺序**（形态→综合征→是否改变处置；保守是"带出口的序贯策略"）、踝足写**负荷剂量学**（并含全专题唯一"预防端证据比治疗端整齐"的部位）。新增部位先定主导维度，不要写成第五份「保养指南」。
- **底座页独占**：四种组织（肌腱 / 腱鞘滑囊 / 关节面 / 周围神经）对"该加负荷还是该减负荷"的答案表、无症状人群形态异常总表、`How Big Is Better` 那张 MID 读法表、与脊柱的接缝（颈痛是**结局标记**、double crush 机制未获支持、**排除 ≠ 归因**）。分册只写各自部位独有的那段试验史与数字，**同一结论只有归属页展开，其它页一律链接**；MID 表里只留判读结论，具体效应值交回分册。
- ⚠️ **口径同前两棵子树**（机制 + 自我管理，不收录注射药物与剂量、手术术式、诊疗路径、指南推荐等级），但本专题额外禁止**个体化训练编排**——不写"3 组×15 次""负荷调到 X%"这类可照做的处方，只写到"哪些量可调、以及按什么判读"为止。页首一律 `> [!WARNING]` 声明口径 + 该页红旗。
- ⚠️ **引用纪律是本库最严的一档**（这个题目的伪方法与二手健身内容比减重更多）：
  1. **写作前先做事实简报**，逐条走 PubMed eutils 核 PMID + 标题 + 年份 + 期刊，并给每条标注「摘要级」还是「仅标题级」。
  2. **「仅标题级」的条目只能写方向，不许出现数字**；简报的 `Unverified` 清单是硬禁区，正文一个都不许写进去（宁可留一句"本次未核实到"）。
  3. **动物证据必须显式标注是大鼠/动物**，不得写成人体结论；**跨部位外推必须标注来源部位**（如 pain-monitoring 那个 RCT 是**跟腱、n=38**，写到膝就是外推）。
  4. **收尾跑一次机器校验**：把全部 References 的 PMID 逐条回 `esummary` 比对标题与期刊缩写（agent 起草的引用常被意译、改大小写、或挂到别的论文上；本库已出现过期刊张冠李戴）。
  5. 常见反直觉禁区：肩**不存在**"某学会已正式废除 impingement 术语"的声明（只能说试验与综述实际改用了 SAPS）；踝扭伤"30%–70% 转慢性"**无一手来源**，用首次扭伤后 3/6/12 个月症状消退曲线代替；"半月板切除会毁掉关节"不被 RCT 支持（十年随访显示两组影像进展无差异）；保守组转手术**不等于**保守失败。
- 固定交叉点：`Spine_Health/Posture_and_Load.md`（**红旗表与 24 小时判读规则的母本，只引用不重述**）、`Spine_Health/Cervical_Spondylosis.md`（神经根型与"颈痛是结局标记"）、`Sports/Anatomy.md`（渐进超负荷的一般原则）、`Weight_Management/`（体重改变的是峰值负荷）、`Medicine/Diagnosis.md`（鉴别与危险分层的方法学）、`Medicine/Basic_Medicine.md`（解剖学入口——⚠️ `Medicine/Anatomy.md` 目前尚未入库，不要挂链到它）。
- 领域枢纽是 `Sports/Sports.md`（它是**四条线**：解剖 / 减重 / 脊柱 / 关节肌腱，改子树时同步那个数字与 Links）。

## Higress 笔记的组织（`docs/CS/Framework/Higress/`）

2026-10 拆分，`Framework/` 里第一个「枢纽 + 多分册」形态的中间件子树（原先是一篇平面笔记）：

- 结构为 `Higress.md`（枢纽，含**三条贯穿主线：先问能力在哪一层 / 插件行为由 phase 与 priority 决定而非插件名 / 二手描述普遍比官方文档乐观，而文档又比源码乐观**）+ **14 篇分册**。九篇机制分册：`Architecture.md`、`AI_Gateway.md`、`Plugin_System.md`、`Wasm_Development.md`、`Traffic_Governance.md`、`Service_Discovery.md`、`Security_and_Auth.md`、`Observability.md`、`Deployment_and_Ops.md`；五篇**源码级**（断言带 `路径:行号`）：`Config_Pipeline.md`（链路逐跳）、`Source_Map.md`（模块地图与注解总表）、`Service_Registry_Internals.md`（`registry/` 实现）、`Standalone_and_AllInOne.md`（独立部署仓）、`Certificates_and_ACME.md`（自动签发实现）。**枢纽沿用原文件名 `Higress.md`，全库原有 12 处入链不受影响**——拆分不改名、不移动，这是本子树的做法。
- **分册按「机制差异最大的维度」切开，不按功能清单平铺**：架构页的重心是**翻译链 + pilot fork 边界**（四个配置入口 → Istio 资源 → xDS）；AI 网关页是**能力分布在三层**（Wasm 插件 / 控制台路由层 / 网关内置 filter，模型级 fallback 只在第二层）；插件体系页独占**阶段与优先级总表**；流量页是限流与灰度各自的多套入口；服务发现页是 `McpBridge` 与 destination 命名规则；安全页是"哪些认证插件走 consumer 模型"这个归类问题。加新分册前先定主导维度，不要写成第二份「Higress 功能大全」。
- ⚠️ **两处共用件只引用不重述**：`Plugin_System.md` 的 phase/priority 总表、`Wasm_Development.md` 的 cluster 寻址规则。本子树多条结论都由它们推出——"缓存命中会绕过 token 限流与配额"、"Redis 与追踪后端必须先注册成服务来源"、"`redis.static` 不写端口连的是 80"。
- ⚠️ **信源与核实口径（两层）**：这个题目二手博客与生成式资料泛滥，**第一层是官方文档站**——正文的字段名、默认值、端口、枚举必须回 `higress.ai/docs/latest/` 逐条核实；**第二层是 v2.2.5 源码**，凡文档与源码冲突**一律以源码为准**，且偏差散在各页正文里说（本子树不单开"偏差"节）。取文档正文的做法：`curl` 抓 Astro Starlight 页 + 正则抽 `<div class="sl-markdown-content">`（**WebFetch 抓这些页会 120s 超时**）；**文档 URL 一律取自 `https://higress.ai/llms.txt`，不要凭印象拼路径**（`higress.io/en/docs/...` 返回 404）。取源码的做法：`git clone --branch v2.2.5`（主仓）与 `--branch aio-v2.2.5`（`higress-standalone`，独立部署形态）。⚠️ 但**不要假定本机有源码树**：`raw.githubusercontent` / `cdn.jsdelivr.net` / `unpkg` / `registry.npmjs.org` 在部分网络下全不可用，`api.github.com` 共享 60/小时极易打光，整仓 clone 与 blobless sparse clone 都可能超时失败——**没有源码时一律降级成文档口径并把"需回源码确认"的项显式写进该页 `## Unverified`**；有源码时，源码级断言必须带 `路径:行号`（相对仓库根、可回 tag 复核），不许凭函数命名推断。**每篇分册末尾都有 `## Unverified`，这是本子树的固定结构，也是硬禁区：那里面的东西一条都不许写进正文。**
- ⚠️ **已证伪、禁止再写回正文的清单**（都曾以"事实"形态流传）：`ai-security-guard` 的 "block / mask / audit 三种处置"（只有检查+拒绝，脱敏属 `ai-data-masking`）；"WAF 依赖 ModSecurity 引擎"（底座是 Coraza，兼容的是 SecLang 与 Phase 规范）；"多 API Key 轮询"（文档原文是随机）；"模型级 fallback 是 `ai-proxy` 的能力"（在控制台 AI 路由管理的降级配置）；指标端口 15090（三处证据只有 15020）；"LITE_METRICS 精简指标开关"（无对应字段）；"50+ 官方插件"（文档站标 41）；"本地限流配 100 QPS、3 副本实际约 300 QPS"（无出处；官方"每实例"口径是 `higress.io/route-limit-rps|rpm`，且带默认 **5 倍** burst 放大）；"nacos 可作 MCP server 注册源"（仅 `nacos3`，且这条限制在源码里是**软校验**——nacos2 配了只打 error 日志后静默跳过）；"Http2Rpc 支持 Dubbo3 Triple"（官方逐字"暂不支持 Triple 协议"，Triple 走 gRPC 直接代理）；语义缓存阈值字段 `similarityThreshold`（实为 `vector.threshold` + `vector.thresholdRelation`，且默认组合对 Cosine / DotProduct 永不命中）。
- ⚠️ **源码核对后推翻的三条（含本库自己上一版的错误）**：① **`hgctl config` 确实存在**（`hgctl/pkg/config_cmd.go:45-50`，是抓 xDS 的 all / bootstrap / cluster / endpoint / listener / route），文档站 hgctl 页没提它——旧版把它写成"不存在的子命令"是**反了**；`profile` / `install` / `upgrade` 等是 root 的子命令。② **`wrapper.ProcessStreamDone` 与 `ProcessStreamDoneBy` 两个名字都真实存在**（前者见主仓 `plugins/wasm-go/pkg/mcp/server/plugin.go:910`，后者是文档 SDK 页形态；`wrapper` 包在外部模块 `github.com/higress-group/wasm-go`，本地不可枚举导出项），不许再写"其中一个不存在"。③ **文档的 41 款插件不都在 wasm-go**：认证基础族（`key_auth` / `basic_auth` / `jwt_auth` / `hmac_auth` / `oauth` / `bot_detect` / `request_block` / `key_rate_limit` / `custom_response` 等）在 **`plugins/wasm-cpp/`（snake_case、bazel）**，`ai-data-masking` 在 **`wasm-rust/`**；而 `plugins/wasm-go/extensions/` 有 **53** 个目录、约 20 个没有文档页（`mcp-router` 就在此列——**存在性成立、语义未读**，旧版"不存在 mcp-router"是错的）。另有一批源码事实值得常驻：**pilot fork 与 Higress 控制器同进程**（`go.mod:302-314` replace + 共享 `*xds.DiscoveryServer` 指针，不是两个服务）、**配置是 pilot 反向 pull、每次 List 全量重算、Higress 侧 debounce 是死字段**、**`higress-config` 的 `mesh` 段不走 Higress 解析**（注入的是 `meshwatcher.NewTestWatcher` 空对象）、**ACME 只有 HTTP-01 且多副本零互斥**、**独立部署的 apiserver 是 `sample-apiserver` fork、CR 存 Nacos 或文件树而非 etcd**。
- 领域枢纽是 `Framework/README.md` 的 `Service Mesh and Gateway` 一节（与 Istio 子树并列）；`docs/CS/CS.md` 的云原生一节也挂了入口。
- 固定交叉点：`Istio/Istio.md`（xDS 与 pilot 的母本）、`Istio/Envoy.md`、`Istio/WasmPlugin.md`（Higress 的 `extensions.higress.io/v1alpha1` 与 Istio 原生 CRD 的关系）、`Istio/TrafficManagement.md`、`Istio/Security.md`、`Istio/Observability.md`、`Spring_Cloud/gateway.md` 与 `Spring_Cloud/Alibaba.md`、`Container/k8s/Ingress.md`、`CN/nginx/compare.md`（ingress-nginx 停维与迁移动机）、`nacos/Nacos.md`、`Dubbo/Dubbo.md`、`gRPC/gRPC.md`、`consul/Consul.md`、`eureka/Eureka.md`、`AI/AI.md` 与 `AI/LLM/LLM.md`（AI 网关的模型侧）。新增内容优先链到这些已有页，不要重复新建。

## Linux 内核笔记的组织（当前主力方向）

`docs/CS/OS/Linux/` 是全库最活跃的子树，组织规则容易踩错：

- **`Linux/Linux.md` 是唯一枢纽**，全库被引最多的文件，**不要改名**（`Linux/` 下没有 `README.md` 是全库常态——很多目录都缺，别顺手新建）。
- **`Linux/` 根目录放横切机制**（不属于单一子系统）：`Interrupt.md`、`Calls.md`、`timer.md`、`workqueue.md`、`LXC.md` / `namespace.md` / `cgroup.md` / `SELinux.md`、`KVM.md`、`Swap.md`、`ZeroCopy.md`、`performance.md`、`Architecture.md`、`Experience.md`、`build.md`。
- **子系统各建子目录**：`proc/`（进程/调度/信号/IPC）、`mm/`、`fs/`、`net/`、`IO/`、`Lock/`、`dev/`、`boot/`（启动链）、`module/`、`struct/`（内核数据结构）、`Tools/`、`Distribution/`。
- **较新的两个子目录**（2026-10 新增，各有独立 README 枢纽）：`cgroup/`（v2 三篇：知识地图 / 控制器接口 / 委派实践；根目录的 `cgroup.md` 保留为 **v1 视角**入口）、`PM/`（电源管理六篇：知识地图 / cpuidle / cpufreq / suspend / runtime PM / devfreq）。
- **新增子目录后必须回 `Linux.md` 挂入口**（踩过：目录迁移完忘了挂，新目录的 README 引用数一度为 0）。
- ⚠️ **`Linux/0.11.md` 讲的是 Linux 自己 1991 年的早期版本**（`bootsect.s` / `setup.s` / `head.S` / `init/main.c`），是现代内核的直系祖先，**不是教学内核**，不要迁到 `OS/` 根或与 xv6 / rCore / osask 并列。
- ⚠️ **`OS/Boot/` 与 `OS/Linux/boot/` 是两个不同目录**：前者只有旧的 `Grub.md`，启动链主题在后者（`README.md` / `Start.md` / `init.md` / `U-Boot.md` / `arm.md` / `crash.md`）。
- ⚠️ `mm/memory.md` 是 **boot 阶段的初始化笔记**，**不是内存子系统总入口**（全站有旧链接把它当 "Linux Memory"，属历史错配）。
- ⚠️ **`struct/struct.md` 只讲 llist**，文件名覆盖面远大于内容，是历史沿用名；`struct/` 的地图以 `struct/README.md` 为准。同理 `Tools/Tools.md`（命令速查表）与 `Tools/README.md`（笔记导航）**不是一回事**。
- ⚠️ **标题避免用全角标点**（如 `## freezer：冻结与终止`）：`validate_links.py` 的 `anchors_of()` 会按全角冒号把标题切成两个锚点，与 docsify 的 `slugify()` 行为不一致，导致 BAD ANCHOR 误报。**标题统一英文后此坑基本自然消除**，但新增标题仍应避免全角 `：（）、，` 与 `→`；中英混排标题用**半角空格**分隔。

**内核源码核实**：**先确认本机有没有源码树**——

```bash
ls -d ~/Tools/linux-* ~/src/linux-* /usr/src/linux-* 2>/dev/null
```

有就优先用本地树（`grep` 最快，还能跨文件检索）；没有再走下面的远程端点。

远程端点用 kernel.org 的 `plain` 接口。**tag 必须写 `v7.2`**（真实 tag 就是 `v7.2` = 7.2.0；**`v7.2.7` 不存在**，写错拿到的是 404 HTML，不是源码）：

```bash
K="https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/plain"
curl -sL -m 40 "$K/kernel/panic.c?h=v7.2"          # → 纯文本源码
```

**端点可用性随机器与网络而变，下面只是某次实测记录，换环境必须重测**：`elixir.bootlin.com` 有 Anubis 反爬，`/source`、`?raw=1`、`/A/` 简写、`/api/v1/source/` 都可能返回 **HTTP 200 但正文是一段约 4KB 的 "Making sure you're not a bot!"** —— 人工浏览可用，自动化不可靠。GitHub API 有 403 限流、`raw` 有 429。**所以"是否真拿到了内容"要看 `wc -l` 与首行是不是 `<!DOCTYPE html>`，不要只看 HTTP 状态码。**

**四个必须知道的操作坑**（都实测踩过）：

1. **判断文件是否存在不能只看 `curl -w %{http_code}`** —— 该状态码会因缓存给出过期值（曾把 404 的 2932 字节 HTML 当成正常响应，导致"文件存在"的错误结论，进而引用了不存在的符号）。可靠做法：`wc -l` 看行数 + `head -1` 判断是否 `<!DOCTYPE html>`。
2. **猜路径极易落空，v7.2 大量文件已搬迁/改名**。用 tree 页取真实清单（比 `Makefile` 反推更准，能拿到未被当前配置编译的文件）：
   ```bash
   curl -sL "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/fs/btrfs?h=v7.2" \
     | grep -oE "fs/btrfs/[a-z0-9_-]+\.(h|c)" | sort -u
   ```
   搬迁大户：`kernel/tty.c` → 拆成 `drivers/tty/tty_{io,ioctl,jobctrl,buffer,ldisc}.c`；`kernel/crash.c` → `kernel/crash_core.c` + `crash_reserve.c`；`fs/fuse/fuse.h` → `fuse_i.h` + `dev.h`；`drivers/input/core.c` → `input.c`；`fs/btrfs/*.h` 改**下划线命名**（`block-group.h`/`delayed-ref.h`）。
3. **结构体定义可能不在你以为的头文件里** —— 例如 btrfs 核心定义搬到了 **uapi 头** `include/uapi/linux/btrfs_tree.h`；`struct btrfs_key` 不在 `fs/btrfs/` 下。
4. **大批量 grep 偶发返回空结果**：对确认含目标串的大文件（数千行）执行 `grep` 曾多次返回空，而同样的检索改用专用搜索工具（Grep / ripgrep）或把源码落盘后再 `grep` 却正常。**若 grep 结果与预期矛盾，换检索方式重试，不要据此认定"符号不存在"** —— 这类"不存在"的结论往往正是旧资料里 API 已删除的来源。

**文件命名反推**：某目录的头文件常与 Makefile 里的 `.o` 名同源（下划线）；`/include/uapi/linux/` 下的类型定义优先于私有头。

**API 迁移强度**（v7.x 相较旧资料改动极大，写作时**必须逐个核实符号是否存在**）：`cpuidle_go_billiard()` 已删、`struct suspend_ops`→`platform_suspend_ops`（成员全变）、cpufreq 的 `name` 从函数指针变定长数组且 `target` 已 Deprecated、`pci_iomap*`→`pcim_*`、`struct spi_master`→`spi_controller`、FUSE 的 `FUSE_CAP_*` 去 `CAP_` 中缀且语义翻转、`FUSE_OPT` 宏移除。**凭印象写必错**。

**版本事实陷阱**：sysctl / feature gate **存在 ≠ 它还生效**。判断"当前实际行为"要读**消费方函数读的是哪个变量**以及**默认值代码**，只看 sysctl 表条目或 gate 状态会写出过时结论。同类陷阱还有两条：① 官方文档可能过时于源码（如 kdump.rst 写 "at least 256M" 而 `DEFAULT_CRASH_KERNEL_LOW_SIZE` 已是 128 MiB）——**常量以源码为准**；② 符号"存在 ≠ 仍是原语义"（`FUSE_INIT_RESERVED` 占 bit 31 导致 64 位能力从 bit 32 起）。

**移动笔记的固定流程**：`git mv` → 脚本全库精确替换旧路径 → grep 复核残留 → **回枢纽页补新目录入口** → 全库死链扫描（路径必须 `urllib.parse.unquote`，否则 `%20` 误报）。同时告知用户 GitHub Pages 上被收藏的 URL 有 404 风险。

**所有锁相关笔记统一放 `Linux/Lock/`**，不要在 `Linux/` 根目录新建 `lock.md`（历史撞名已合并）。

## 渲染管线（index.html）

docsify 4.x，主题 `docsify-darklight-theme` + `themes/vue.css`。

已加载插件：搜索、图片缩放、字数统计（docsify-count）、上下页（pagination）、flexible-alerts、tabs、copy-code、hide-code、remote-markdown、footer（footer-enh）、progress、share、sidebar-collapse、link-preview、emoji、slides、sequence-diagram、puml、plantuml、katex。

**没有页内目录**：`docsify-toc` 插件已整体移除（脚本与 `toc` 配置都删了）。导航靠首页目录树 + 每篇笔记末尾的 `## Links`，**不要在 `index.html` 里把它加回来**。

**不做站点级侧边栏**：`loadSidebar: false` 是既定设计（2026-10-02 用户确认）。**不要生成 `_sidebar.md`，也不要打开 `loadSidebar`** —— 全站导航以首页目录树（`README.md` + `docs/CS/CS.md`）为准。

Markdown 增强写法：

- 公式：` ```tex ` 代码块 → KaTeX 渲染
- 图：` ```dot ` → Graphviz（Viz.js）；` ```sequence ` → 时序图；` ```puml ` / plantuml
- 提示块：`> [!NOTE]` / `[!TIP]` / `[!WARNING]`（flexible-alerts，`style: flat`）
- 标签页：docsify-tabs 语法

**首页专用样式**写在 `index.html` 的 `<style>` 里，选择器以 `.kb-home` 为前缀（`README.md` 用 `<div class="kb-home">` 包裹）。改动首页视觉请改那里，不要把 CSS 塞进 Markdown。

当前配置要点：`name: 'Note'`、`repo: https://github.com/Robinpig/Note`、`loadSidebar: false`、`loadNavbar: false`、`maxLevel: 4`、`sidebarDisplayLevel: 4`、`autoHeader: false`、`externalLinkTarget: '_blank'`、`auto2top: true`，别名 `/.*/_sidebar.md → /_sidebar.md`（侧边栏功能的遗留配置，本项目不生成 `_sidebar.md`，可忽略）。

## 笔记写作规范（必须遵守）

1. **结构顺序**：`## Introduction` 开头 → 正文小节（`##` 子主题、`###` / `####` 细节）→ `## Links` → `## References`。正文不内嵌「来源：…」引用块。
2. **内容标题一律英文**（2026-10-07 执行，取代旧规「标题一律中文」，且**取代更早的「按域区分」**）。除固定英文骨架外，正文小节（`##` 子主题、`###` / `####` 细节）标题一律用英文；正文保持中文、代码 / 配置名 / 产品名保留英文、References 保留原文。标题仍是锚点来源，改名会打断全库 `?id=` 引用，必须同步验证。
   - 固定英文骨架（全库统一三段式，不得汉化）：`## Introduction` / `## Links` / `## References`。
   - **保留原文、不翻译的标题**：**系统 / 算法 / 产品专有名词**（如 `## GFS`、`## Paxos`、`### Bigtable`、`## Consensus`）以及各类代码标识（`qspinlock`、`io_uring`、`SRCU` 等）。**全库标题已完成英化**，这类专名原样保留即可，不要再"译成中文+附英文"。
   - ✅ 描述性概念**译成英文**：`## 消息代理` → `## Message Brokers`、`### 分区日志` → `### Partitioned Logs`；同一中文标题在不同文件**必须译名一致**（如「概述」统一 `Overview`）。
   - ⚠️ **代码块内的 `#` / `//` 注释不算标题，保持中文**。用 `^#{1,4}\s+` 扫描标题时**必须先跟踪 ``` / ~~~ 围栏、跳过代码块内的行**，否则会把 Python/shell 注释（如 `# 1. 定义状态`）误当标题改掉——2026-10-07 全库英化时曾误改 591 行/118 文件，事后靠 `git diff` 定位才全部回滚。
   - ⚠️ **锚点 bug 红线**：docsify 的 `?id=` 链接里**不能写带括号的标题**——半角 `( )` 会被 markdown 链接结构提前截断，全角 `（）` 的链接本库也无 `%` 编码先例、实际写不出。**被 `?id=` 引用的标题不要带任何括号**；确有需要时改用半角且确保该锚点不被 `?id=` 引用。改动任何标题前先 `grep -rn "<file>.md?id=<slug>" docs/`，有引用就同步修并重跑 `validate_links.py` —— 改完立刻验证，别留到收尾。
   - **批量改标题的标准流程**（6000+ 条已跑通）：① 导出目标范围中文标题清单 → ② 定英文译名 → ③ 脚本按文件精确替换标题行（保留 `#` 层级、跳过代码块）→ ④ 收集各批 `old_slug → new_slug` 映射 → ⑤ **按「目标文件路径 + 旧 slug」作用域**统一同步 `?id=`（**绝不能无作用域全局替换**，否则误伤其它文件同名标题）→ ⑥ 三道校验：严格残留扫描（排除代码块）+ `validate_links.py` 全库 **BAD ANCHOR = 0** + `git diff` 排查代码块内误改。
3. **站内链接**一律用 docsify 绝对路径：`/docs/CS/OS/Linux/proc/process.md`；锚点用 `?id=slug`。
4. **slug 规则**（2026-10-02 按 docsify v5.0.0 源码 `src/core/render/slugify.js` 逐条复核；v4.13.1 实现相同。**不要凭标题印象拼**）：
   - `[A-Z]+` → 小写。**对纯 ASCII 标题等价于整串小写**（`MarkWord` → `markword`，`M` 与 `W` 都被小写）；差异只在非 ASCII 大写字母（`École` 保留 `É`）。
   - 删**半角**标点（ASCII 标点 + `\u2000-206F` + `\u2E00-2E7F`）→ **全角标点（：）（，、）与 `→` 一律保留** → 空白转 `-` → 数字开头前缀 `_` → markdown 链接只保留方括号里的显示文本（如 `[文本](https://example.com)` → `text`）。
   - 例：`限额接口（cgroup v2）` → **`限额接口（cgroup-v2）`**；`注意（Attention）` → **`注意（attention）`**。
   - 算不准就当场跑（`slugify()` 定义在 `validate_links.py`，可直接 import）：

     ```bash
     python3 -c "import sys;sys.path.insert(0,'scripts');from validate_links import slugify;print(slugify('标题'))"
     ```
   - ⚠️ `slugify()` 已于 2026-10-02 按 docsify 上游重写：旧版是「整串小写 + 删所有标点」，会把含全角标点的好链接误报成死链。另：全库存在**同文件内重复标题**，docsify 会给第 2、3 个追加 `-1`／`-2` 后缀（`anchors_of()` 已支持）。
   - **改标题会断既有锚点**：动手前先 `grep -rn "<file>.md?id=<slug>" docs/`，有引用就把旧标题保留为独立小节，不要合并掉。
5. **`## Links`** 放 1~6 条最相关的**站内**笔记，只写一行 `- [标题](/docs/CS/OS/Linux/Linux.md)` 这种形式，**链接后不加任何后缀说明**；正文里已出现过的内部链接不重复列入；新增笔记后要回填相关笔记的 Links，形成双向链接。
6. **`## References`** 位于全文最后（`## Links` 之后），放外部文章 / 论文 / 官方文档，每条只写一行标题加链接，不加后缀说明（形式如 `[Linux Kernel Docs](https://docs.kernel.org/)`）。**KEP / RFC / issue 编号必须核实再写**（凭印象填编号、或照旧目录 slug 写 URL，都会 404）。
7. **代码片段**：从内核 / 框架源码摘录时保持原样（含原注释），中文解释写在代码块外的段落里。
8. **图片**放同目录或上级 `img/`，用相对路径引用。
9. **对比与选型优先用 Markdown 表格**。
10. 目录级索引页用 `README.md`，范式参考 [proc/README.md](/docs/CS/OS/Linux/proc/README.md)（叙述性知识地图 + 分节展开）。
11. **枢纽页导航禁止「`## XX 笔记索引` + `笔记|内容` 两列表格」**，必须写成**有因果递进的叙述性章节**（讲清为什么需要它、解决什么问题、与相邻笔记的关系），链接嵌进句子；不必串联全部笔记。表格只用于内容型对照。同层对比型笔记（如 Coze / Dify）之间不补直接互链，横向跳转交给枢纽页。

## 修改前必读的禁区

- **不要重命名或移动 `docs/` 下已有文件 / 目录**。确需移动时必须按上面「移动笔记的固定流程」执行，并先告知用户外链有 404 风险。
- **不要修改 `out/`**（IDE 产物副本）、`src/`、`wiki/`、`knowledge-base/`、`outputs/`。
- `index.html` 只动配置和样式区块，**不要重排脚本加载顺序**（插件依赖 docsify 主脚本先加载）。
- `.obsidian/`、`.claude/`、`.workbuddy/` 是**本机工具目录，都不入版本控制**（`.gitignore` 里忽略了 `.obsidian/`、`.claude`、`.workbuddy`）—— 换机器克隆下来可能根本不存在，**不要依赖、也不要删**。其中 **`.workbuddy` 存的是 Agent 记忆，不是缓存**；**校验脚本不在那里，在已入库的 `scripts/`**。
- 新增链接前先确认目标文件存在。以下目录的入口**不等于目录名**（或存在两级入口），别写错：
  - `CS/BuildTool/` 入口是 `BuildTools.md`（不是 `BuildTool.md`）
  - `CS/Tool/` 无 `Tool.md`，代表文件 `Vim.md`
  - `CS/front-end/` 无 `front-end.md`，代表文件 `Nodejs.md`
  - `CS/Java/` 有两级入口：语言入口与目录地图是 `Java/Java.md`，JDK/JVM 内部机制的枢纽是 `JDK/JDK.md`（写 JDK 源码细节走后者）
  - `CS/SE/` 入口是 `Engineering.md`
  - `CS/Framework/` 无 `Framework.md`，总入口是 `Framework/README.md`（目录级索引页），具体机制在各框架子目录
  - `docs/Test.md` 是测试页，可忽略

## 校验工具（`scripts/`，随仓库入库，不进站点）

| 脚本 | 用途 |
| :--- | :--- |
| `scripts/kb-check.sh` | **一键全量门禁**（推荐入口）：链接校验 + 密度门禁 + 全库 dot 校验 + CDN 可达性（仅告警）；前几项任一不通过即非零退出 |
| `scripts/validate_links.py <file\|dir...>` | **主力校验**：死链 DEAD / 坏锚点 BAD ANCHOR / 相对链接 RELATIVE / 西里尔字母 CYRILLIC（均致命）+ 中英夹杂 GARBLED（告警）。可 `import` 出 `slugify()` 复用 |
| `scripts/analyze_crosslinks.py --root <目录> --dirs <子目录...> [--gate --min-indegree N]` | 量化链入/链出、孤立页、弱链出页；`--gate` 做密度门禁。**目录只能用 `--root`/`--dirs` 传，写位置参数会报错退出**（`-h` 看完整说明）。默认根是 `docs/CS/Framework`，跑别的子树必须显式 `--root`。带 `?id=`／`#` 片段的链接与 `%20` 转义路径**都计入**图；根目录下的散文件（`CS.md`、`Languages.md`）不作为节点 |
| `scripts/check_dot.js <dir...>` | 用站点实际加载的 viz.js 复现 dot 图渲染，防 Graphviz 语法错误导致整页白屏（需 node）。viz.js 地址**从 `index.html` 现读**（改 CDN 不必回来改脚本），失败回退 unpkg；下载内容会校验首行是否 `<!DOCTYPE html>`。离线/被墙机器用 `VIZ_JS=<本地路径>` 指定手工下载的副本 |
| `scripts/check_cdn.sh` | 逐条验证 `index.html` 的外部资源可达。**「页面完全无法渲染」时先跑这个**（需 curl） |
| `scripts/fix_garbled.py` | 修 `validate_links.py` 报的 GARBLED（在 CJK 与 Latin 边界补空格） |
| `scripts/find_hub_gaps.py` | 定位 hub 页 `## Links` 中未链到的子笔记 |
| `scripts/fix_framework_hublinks.py` | 阶段①：框架内 hub 页 Links 补齐，消除孤立页 |
| `scripts/fix_framework_crosslinks.py` | 阶段②：跨框架双向链接矩阵 |

> [!NOTE]
>
> 这批脚本原先放在 `.workbuddy/tools/`，而那个目录被 `.gitignore` 忽略 → 新机器与 GitHub Actions 上都拿不到（CI 直接 `can't open file`）。2026-10-06 已迁到 `scripts/` 并入库，`.gitignore` 里用 `!scripts/*.py` 放行。**不要再把它们挪回被忽略的目录，也不要写死绝对路径**：脚本的仓库根一律由自身位置（`__file__` / `__dirname`）推导，可在任意 cwd 下调用。

`validate_links.py` 的选项：`--verbose` 逐行打印 GARBLED 告警（默认只汇总计数）、`--strict` 把 GARBLED 也当致命。退出码 0 = 通过。

## 站点白屏排查：先验 CDN，再查内容

**外部依赖必须全部挂 `cdn.jsdelivr.net`，不要用 `unpkg.com` 或 `cdn.staticfile.org`**（2026-10-06 实测这两个域名连接失败，而 docsify 核心原本就挂在 unpkg 上 → **整站白屏、任何页面都打不开**，而笔记内容、链接校验、dot 图校验全绿，**极易误判成笔记写坏了**）。

排查「页面无法渲染 / 白屏」的顺序：
1. `bash scripts/check_cdn.sh` —— 外部资源是否都200。
2. `bash scripts/kb-check.sh` —— 才是内容层面（死链 / dot 图语法）。

两个 jsDelivr 坑：**包版本号可能不存在**（`docsify@4.13.0` 是 404，要用不带版本的 `docsify/lib/...`）；写脚本抽 URL 时**先剥 HTML 注释块**，否则已停用的插件（mermaid/disqus 等）会被计入而产生误报。
⚠️ **不要用 headless Chrome 验证这个站点**：`--dump-dom` 会因 viz.js（2.4MB）挂死数分钟。用「curl 验 200 + `node --check` 验语法」代替。

```bash
python3 scripts/validate_links.py docs/CS/Framework/etcd   # 按目录
python3 scripts/validate_links.py docs/CS/Framework        # 按框架
python3 scripts/validate_links.py docs/CS/OS/Linux         # Linux 内核子树
bash scripts/kb-check.sh                                   # 本地全量门禁（范围比 CI 大，见下）
```

**CI 与本地脚本的范围不是一套，别当成等价**（2026-10-06 逐条比对 `.github/workflows/ci.yml` 与 `scripts/kb-check.sh`）：

| 入口 | 覆盖范围 |
| :--- | :--- |
| `.github/workflows/ci.yml`（push / PR，ubuntu-latest） | Framework 链接校验 + Linux 链接校验 + Framework 密度门禁 + Linux 密度门禁，共 4 步 |
| `scripts/kb-check.sh`（本地） | 上述四项 **＋ 消息队列链接校验 ＋ 全库 dot 图可渲染校验**；找不到 node 时自动跳过 dot 校验 |

门禁规则为「无孤立页 + 平均链入 ≥ 3.5」，弱链出页仅告警不阻断。**快照数字不要写进本文件**，需要时现场跑脚本。

> [!WARNING]
>
> `analyze_crosslinks.py --gate` 失败时**退出码为 1**。写 shell 门禁脚本时若只把它放在中间位置，`set -e` 不会捕获（只看最后一条命令的退出码），会出现"打印了不通过却仍然 exit 0"的假通过。`scripts/kb-check.sh` 用 `check()` 包装函数显式检查每一步的退出码——**改这个脚本时务必保留该包装**。

**全库跑 `validate_links.py` 约 1.5 分钟（千余篇）；按目录跑更快。**

站内死链扫描（在仓库根执行，**路径必须 unquote**，否则含 `%20` 的路径全误报）：

```bash
grep -rhoE '/docs/[^)` ]+\.md' docs README.md | sort -u | python3 -c "
import sys, os, urllib.parse as u
for line in sys.stdin:
    p = u.unquote(line.strip())
    if not os.path.isfile('.' + p):
        print('BROKEN:', p)
"
```

代码围栏"不成对"的常见根因是**连续两个开启围栏**；定位法是把围栏按序编号，看奇数位是否出现了纯 ` ``` `。

## 常见任务

**统计各目录篇数**

```bash
for d in docs/CS/*/; do printf "%-24s %s\n" "${d#docs/CS/}" "$(find "$d" -name '*.md' | wc -l)"; done | sort -k2 -rn
```

**新增一篇笔记**

1. 确定归属目录，文件名用术语英文名（同目录内保持风格一致）。
2. 按「笔记写作规范」写正文，结尾补 `## Links` 与 `## References`。
3. 挂进索引：所属目录的 `README.md` 或父级入口页（如 `CS/OS/Linux/Linux.md`）的叙述性章节 / 表格。
4. 在相关笔记的 `## Links` 里补回链。
5. 跑校验（`validate_links.py` + 死链扫描），确认无死链、无坏锚点。工具不在本机时按「校验工具」一节的语义手工核对。

**本地预览**

```bash
python3 -m http.server 8899   # 打开 http://127.0.0.1:8899/index.html
```

## 已知遗留问题

- ✅ **校验脚本入库问题已修**（2026-10-06）：脚本原在 `.workbuddy/tools/`（被 `.gitignore` 忽略），CI 却调用它们 → 新机器与 Actions 上必然缺文件。已迁到 `scripts/`，`.gitignore` 加 `!scripts/*.py` 放行。**遗留的小不对称**：`ci.yml` 仍只跑 Framework + Linux 两项，而 `scripts/kb-check.sh` 多跑 MQ 校验与全库 dot 校验 —— 若想让 CI 与本地完全一致，把 `ci.yml` 的 4 个 step 换成一句 `bash scripts/kb-check.sh` 即可（ubuntu-latest 自带 node，可直接跑 dot 校验）。
- ✅ **`check_dot.js` 的 viz.js 源与站点漂移已修**（2026-10-06）：脚本硬编码 `unpkg.com`（站点本体早已全量挂 jsdelivr），本机连不上 unpkg 时这一步必失败，看起来像"内容写坏了"其实是取不到渲染器。现在**从 `index.html` 现读** viz.js 地址、失败回退 unpkg、下载内容校验首行是否 `<!DOCTYPE html>`、超时压到 connect 8s / 总 30s，离线或被墙的机器用 `VIZ_JS=<本地路径>` 指定手工下载的副本即可跑。
- ✅ **`analyze_crosslinks.py` 漏计带锚点的链接已修**（2026-10-06）：旧正则只匹配 `](/docs/x.md)`，凡是 `?id=` 锚点链接与 `%20` 转义路径**全部不计入图**，导致枢纽页链出被系统性低估、门禁数字偏冷（边只增不减，修完门禁阈值不用动）。同时它的真实接口是 `--root`/`--dirs`，而本节旧版写成位置参数 `[dir...]` —— 已改正文档，并让脚本误用位置参数时打印用法而非只报"未知参数"。
- 部分目录缺同名入口 md（见禁区一节），目录索引只能链接到具体笔记。
- 全库仍有若干主题零覆盖（DAMON、dm-crypt / LUKS、md / RAID、kTLS、Landlock），部分主题偏薄（livepatch、kdump、pidfd、psi、MPTCP）。定时任务主题的缺口（Python / Rust / C++ 定时器、Go 运行时深处、K8s CronJob、crontab / systemd timer）单独记在 `docs/CS/SE/Scheduled_Task.md` 的 Open Gaps 一节，**以那里为准，不在本文件重复列**。
