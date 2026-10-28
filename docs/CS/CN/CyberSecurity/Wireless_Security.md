## Introduction

无线安全的根本困境：**链路是广播介质，没有物理边界**。攻击者不需要进机房、不需要插网线，坐在停车场就能收到全部帧——这与有线网"接上线才有流量"的模型有代差。WiFi 的物理层与接入机制（802.11 帧、CSMA/CA、CSMA/CD）见 [CN](/docs/CS/CN/CN.md) 的无线章节，本页讲安全体制的演进：WEP 为何破产、WPA2 的两次重击（KRACK 与离线口令）、WPA3 的 SAE 设计与其自身的 Dragonblood 教训。企业侧的 802.1X/EAP/RADIUS 见 [Authentication](/docs/CS/CN/CyberSecurity/Authentication.md)。

## WEP: How It Failed

WEP（Wired Equivalent Privacy，1997，随 802.11 原始标准发布）想达到"等价于有线的机密性"，设计上是 RC4 流密码 + 24 位 IV + CRC-32 完整性校验。三个缺陷叠在一起使其彻底破产：

- **24 位 IV 太小**： busy 网络上 IV 数小时即重复，而 RC4 的密钥调度对 IV 敏感——相同 IV + 相同密钥 = 相同密钥流，重放即解；
- **FMS 攻击（2001）**：Fluhrer-Mantin-Shamir 发现某些"弱 IV"会以可测偏差泄漏密钥字节，之后 PTW 改进（2007）把所需数据量降到数万帧——aircrack-ng 几分钟出钥匙成为现实；
- **CRC-32 不是 MAC**：校验和线性可调，攻击者翻转密文比特后能重算校验和让接收方照单全收——完整性形同虚设。

结论没有任何悬念：**WEP 已废弃，任何场景都不应再使用**（部分极老设备因硬件锁死只能跑 WEP，正确做法是隔离在独立 VLAN 并只开放最小必要端口）。它今天只剩一个教学用途：一个关于"密码学组件正确、组装方式错误"的完美案例。

## WPA and WPA2

**WPA（2003）**是 802.11i 定稿前的补丁：TKIP 在不动旧硬件的前提下修掉 WEP 的即时致命伤——每包一密钥（per-packet key mixing）、序列计数器防重放、Michael 校验值（弱 MAC，但有比没有强）。定位是"过渡"，TKIP 自身已被证明可被侧信道破解（Schepers/Vanhoef 2019）并在 802.11-2012 起弃用。

**WPA2（2004，802.11i 完整版）**是此后近二十年的主力， Personal 与 Enterprise 两条路：

- **Personal（PSK）**：所有设备共享同一把 PMK（由口令经 PBKDF2 派生）。接入时跑**四次握手**：AP 发 ANonce、客户端回 SNonce，双方用 `PTK = PRF(PMK, ANonce, SNonce, AP_MAC, STA_MAC)` 派生会话密钥（拆成 KCK 管 EAPOL 帧认证、KEK 管 GTK 分发、TK 管数据加密），最后 AP 把组播 GTK 加密送给客户端。数据面用 **CCMP**（AES-CCM，强制）或 GCMP（AES-GCM，可选）；
- **Enterprise（802.1X）**：PMK 由 RADIUS 服务器经 EAP 方法动态产生（推荐 EAP-TLS，见 [Authentication](/docs/CS/CN/CyberSecurity/Authentication.md)），每人一密钥、可吊销、可轮换——这是企业无线的正确形态。

两次把这个协议打穿的研究值得记住，因为它们的教训超出 WiFi：

**KRACK（Key Reinstallation Attack，2017-10 披露，CCS 2017）**——Mathy Vanhoef 与 Frank Piessens 发现 WPA2 的**协议级**缺陷：四次握手的消息 3 在丢包时会重传，而规范不要求在重连时更换密钥；攻击者重放消息 3，客户端便重新安装已用的密钥、把 nonce 与重放计数器**重置**——nonce 一旦重用，AES 等流式加密即可被攻击：解密、重放、甚至注入。涉及 CVE-2017-13077 至 CVE-2017-13088 共 10 个编号（VU#228519），影响所有"正确实现"——Linux/Android 广泛使用的 wpa_supplicant 尤其惨：可被诱导安装**全零密钥**，等于当场剥掉加密（wpa_supplicant 2.7 修复）。2018 年 CCS 的后续论文（Release the Kraken）又推广到组播密钥、TDLS、快速 BSS 切换并审计了各家补丁。教训：**握手协议的正确性不能靠"实现会小心"保证，KRACK 打击的是规范本身**。

**离线口令爆破**——PSK 模式的固有软肋：攻击者被动捕获一次四次握手（或利用 2018 年披露的 PMKID：AP 的首条 RSN 报文里直接带 PMKID，无需等客户端）即可离线跑字典/彩虹（hashcat -m 22000）。8 位以下口令在 GPU 上以小时计。个人网络的唯一对策是长口令（14+ 位随机或 4 词以上 diceware）；企业对策是根本不用 PSK。

**PMF（802.11w，管理帧保护）**：WPA2 里可选的机制，给 deauth/disassoc 这类明文管理帧加 MAC——不禁用但让伪造管理帧可检测，是对付去认证洪水（踢用户下线、逼强制门户重认证）的手段。WPA3 起强制。

## WPA3

WPA3（Wi-Fi Alliance 2018-06 发布认证）的核心是把 PSK 模式的离线爆破连根拔掉：

- **Personal 换用 SAE（Simultaneous Authentication of Equals，基于 Dragonfly PAKE）**：握手本身是抗离线的——即使攻击者捕获了握手，也只剩在线字典攻击（每次尝试都要与 AP 交互、可被限速），且提供**前向保密**（历史流量不因口令泄露而解密）。SAE-PK 扩展（2020）再加一层公钥认证，专防降级与伪 AP；
- **Enterprise 192-bit 模式**：对齐 CNSA 套件（GCMP-256、ECDH/ECDSA P-384、BIP-GMAC-256），面向政府/金融等高保证场景；
- **OWE（Opportunistic Wireless Encryption，RFC 8110）**：给"开放网络"（咖啡店、机场）也加上无认证的加密——不解决"连的是谁"，但解决"同咖啡馆的人能否嗅探我"；
- **Transition 模式**：同一 SSID 同时广播 WPA2 + WPA3，让存量设备能连——**这也是降级攻击面**，见下。

Wi-Fi CERTIFIED 7（2024-01-08 发布，基于 IEEE 802.11be）把 **WPA3 与管理帧保护列为认证强制项**；2026-01-06 起 Wi-Fi 7 认证扩展到 20 MHz 窄带 IoT 设备，安全要求不变。

## Dragonblood: WPA3's Own Lesson

WPA3 发布不到一年，Vanhoef 与 Ronen 交出了它的答卷——**Dragonblood**（2019-04 披露，论文 *Dragonblood: Analyzing the Dragonfly Handshake of WPA3 and EAP-pwd*，IEEE S&P 2020；工具与细节见 wpa3.mathyvanhoef.com）：

- **降级攻击**：transition 模式 + 安全组降级，攻击者迫使客户端退回 WPA2，然后用现成的 WPA2 工具爆破口令（VU#871675）；
- **侧信道**：SAE 的 Dragonfly 握手中 hash-to-curve 的密码编码存在**时间与缓存侧信道**（CVE-2019-9494），泄漏信息可做 password-partitioning——把字典空间按泄漏切分再逐一验证，8 位小写口令的成本被研究者压到 **1 美元以下的 EC2 算力**；
- **补丁反被将一军**：Wi-Fi 联盟私下建议厂商改用 Brainpool 曲线规避，结果 Brainpool 曲线本身引入第二类侧信道（CVE-2019-13377）；FreeRADIUS 的 EAP-pwd 实现也出过信息泄露（CVE-2019-13456）与 invalid-curve 认证绕过（CVE-2019-11235，构造恶意椭圆曲线点即可冒充任意用户）。

Dragonblood 的价值在方法论：**"闭门制定的安全建议 + 不公开的标准细节"被证明是负资产**——研究者两次绕过官方 mitigation，最终推动协议自身重新设计。对工程实践的含义：WPA3 远好于 WPA2-PSK，但不要把它当作免维护的终点，固件更新仍然重要。

## Attacks Beyond the Cipher

无论哪代加密，帧的结构与管理的粗糙都可被利用：

- **Evil twin / 伪 AP**：同名 SSID + 更强信号诱客户端关联，配合强制门户钓口令。SAE-PK 与企业级证书校验是解药；个人用户唯一信号是"突然要求重新输入 WiFi 密码"；
- **去认证洪水**：伪造 deauth 帧反复踢客户端（也用于逼 WPA2 客户端重连以抓握手）。WPA2 的 PMF / WPA3 的强制 PMF 是正解；
- **FragAttacks（2021）**：Vanhoef 发现 802.11 **标准设计层**的缺陷组（帧聚合、分片、混合密钥），可注入明文帧、绕过加密影响所有代际（含 WPA3），靠固件补丁修复——与 KRACK 同属"规范即攻击面"家族；
- **Kr00k（CVE-2019-15126，2020）**：部分 Broadcom/Cypress 芯片在客户端断开连接后把会话密钥重置为**全零**，此后流量可用零密钥解密——半是规范外行为，半是空密钥检查缺失。

## Operational Checklist

企业无线（2026-10 口径）：

1. **WPA3-Enterprise + EAP-TLS**（客户端与 RADIUS 服务器双向证书）是基准答案；WPA2 只作为 transition 兼容保留并计划退出；
2. **PMF 强制开启**（WPA3 认证已强制，WPA2 网络要显式配置 `pmf=required` 等价项）；
3. **RADIUS 服务器证书必须被客户端校验**（PEAP 类部署的最高发事故：不验证证书 = 伪 AP 可钓口令）；
4. PSK 仅用于隔离的访客 VLAN，且每场合一换；
5. 监控去认证风暴与陌生 BSSID（同名 SSID 不同 MAC 即告警）。

个人/家庭：WPA3-SAE + 长口令；固件保持更新（Dragonblood/FragAttacks/Kr00k 全是固件级修复）；别用"以 PIN 连接"（WPS，其离线 PIN 爆破 2011 年即被公开破解，禁用为妙）。

## Comparison

| 代际 | 加密 | 认证/密钥 | 完整性 | 已知死穴 | 现状 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| WEP（1997） | RC4 + 24-bit IV | 静态共享密钥 | CRC-32（非密码学） | FMS/PTW 离线破解 | 废弃 |
| WPA（2003） | TKIP（RC4 混合） | PSK 或 802.1X | Michael | TKIP 侧信道 | 淘汰 |
| WPA2（2004） | CCMP（AES-CCM） | PSK 或 802.1X | CCMP | KRACK；PSK 离线爆破；PMF 可选 | 存量主力 |
| WPA2 + PMF | 同上 | 同上 | 管理帧保护 | PSK 离线爆破仍在 | 过渡底线 |
| WPA3（2018） | GCMP | SAE（前向保密）/ 802.1X | GCMP-128/256 | Dragonblood 侧信道；transition 降级 | 新部署基准，Wi-Fi 7 强制 |

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [Authentication](/docs/CS/CN/CyberSecurity/Authentication.md)
- [Attack](/docs/CS/CN/Attack.md)
- [Cryptography](/docs/CS/CN/CyberSecurity/Cryptography.md)
- [VPN](/docs/CS/CN/VPN.md)
- [IDS IPS](/docs/CS/CN/CyberSecurity/IDS_IPS.md)

## References

1. [KRACK Attacks: Breaking WPA2](https://www.krackattacks.com/)
2. [Dragonblood: Analyzing the Dragonfly Handshake of WPA3 and EAP-pwd（wpa3.mathyvanhoef.com）](http://wpa3.mathyvanhoef.com)
3. [FragAttacks: Fragmentation and Aggregation Attacks](https://www.fragattacks.com/)
4. [Kr00k - CVE-2019-15126](https://www.kr00k.info/)
5. [Wi-Fi Alliance - Wi-Fi CERTIFIED WPA3](https://www.wi-fi.org/discover-wi-fi/wi-fi-certified-wpa3)
6. [NIST SP 800-97 - Establishing Wireless Robust Security Networks: A Guide to IEEE 802.11i](https://csrc.nist.gov/pubs/sp/800/97/final)
