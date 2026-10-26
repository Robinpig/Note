## Introduction

密码学是网络安全的数学地基：[TLS](/docs/CS/CN/TLS.md)、[IPsec](/docs/CS/CN/Security.md)、WPA3、SSH 这些协议没有任何"自有魔法"，全部由本页的几样原语——对称加密、哈希、MAC、非对称加密、数字签名、密钥派生——按固定配方组装而成。读懂原语的边界（各自解决什么问题、什么参数算安全、哪些已被淘汰），才能读懂协议层的每一个设计决策，也才能看懂 [Attack](/docs/CS/CN/Attack.md) 里那些攻击为什么成立。

概念掠影（CIA、密码学与隐写术的区分）见 [Security](/docs/CS/Security/Security.md)；本页按"协议怎么用这些原语"组织，算法现状以 2026-10 核实的标准与部署为准。公钥绑定的身份问题不在本页，见 [PKI](/docs/CS/CN/CyberSecurity/PKI.md)。

## Symmetric Ciphers

对称加密用同一把密钥加密与解密，是批量数据的唯一现实选择——非对称算法的速度比它低两三个数量级。分两组：

- **分组密码（block cipher）**：把明文切成固定长度的块逐块变换（AES 块长 128 bit）；
- **流密码（stream cipher）**：生成密钥流与明文逐比特异或（ChaCha20）。

算法谱系与现状（2026-10 核实）：

| 算法 | 块长/结构 | 状态 |
| :--- | :--- | :--- |
| DES | 64 bit 块、56 bit 密钥 | 1999 年已被分布式暴力破解；FIPS 46-3 于 2005 年撤销，仅存于遗留系统 |
| 3DES | 三轮 DES | NIST SP 800-131A Rev.2 起弃用，2023 年后不再批准用于加密 |
| AES | 128 bit 块、128/192/256 bit 密钥 | **现行标准**（FIPS 197），硬件 AES-NI 普及后无性能理由不用它 |
| ChaCha20 | 流密码 | RFC 8439；无 AES-NI 的移动端/嵌入式上快于 AES，TLS 1.3 与 WireGuard 的备选套件 |
| SM4 | 128 bit 块 | 中国商用密码算法，国密合规场景使用 |

分组模式比算法本身更容易踩坑，因为模式决定"块与块之间怎么关联"：

| 模式 | 语义 | 坑 |
| :--- | :--- | :--- |
| ECB | 每块独立加密 | 相同明文块产出相同密文块，模式即泄露结构，任何场景都不该用 |
| CBC | 块间链式 + IV | 需随机 IV；padding oracle 攻击的载体 |
| CTR / GCM | 计数器模式流式化 | **nonce 绝不可重用**；GCM 重用 nonce 同时泄漏认证密钥，属灾难性错误 |
| GCM / CCM | AEAD：加密 + 认证一体 | TLS 1.3 只保留 AEAD；GCM 见 NIST SP 800-38D |
| XTS | 面向磁盘的 tweak 模式 | 只为存储介质设计，不用于网络报文 |

> [!NOTE]
>
> **"加密"和"防篡改"是两件事。** 单有对称加密不保证完整性：攻击者翻转密文比特，对应明文块会以可预测方式变化。现代协议因此一律用 AEAD（如 AES-GCM、ChaCha20-Poly1305）把两者捆在一起，这正是 TLS 1.3 只保留 AEAD 套件的原因。哈希与 MAC 是另一条达到完整性的路径，见下。

## Hash Functions

哈希把任意长输入压缩成定长摘要，协议里用它做指纹（完整性）、承诺、KDF 配料与签名前置。三条性质递进：抗第一原像（给定摘要反推输入）、抗第二原像（换不掉摘要）、抗碰撞（找不到两个同摘要输入）。

谱系与现状：

| 算法 | 输出 | 状态 |
| :--- | :--- | :--- |
| MD5 | 128 bit | 碰撞攻击 2004 年即实用化，只能用于非安全校验和 |
| SHA-1 | 160 bit | 2017 年 Google SHAttered 公布首例实用碰撞；FIPS 186-5 起禁止用于生成签名，仅允许校验历史签名 |
| SHA-2（SHA-256/384/512） | 224~512 bit | **现行主力**（FIPS 180-4），TLS 1.3、证书、代码签名的事实标准 |
| SHA-3（Keccak） | 可调 | FIPS 202；与 SHA-2 机制不同（海绵结构），作为算法多样性备份存在 |
| BLAKE2 / BLAKE3 | 可调 | 未进 NIST 标准但工程流行（BLAKE2b 用于 Argon2、Zstd、WireGuard 的哈希），纯软件速度快于 SHA-2 |

两个反复被问的边界：

- **哈希不是加密**，没有密钥，不可逆只是计算难度而非数学保证；
- **长度扩展攻击**：对 `H(secret || message)` 这种朴素构造，攻击者可在不知道 secret 的情况下延展 message 并算出合法摘要——所以"带密钥的哈希"必须用 HMAC 这类显式构造，而不是把密钥拼进输入。

## MAC

消息认证码用对称密钥为消息生成验证标签，同时提供完整性与（对称意义上的）来源认证：只有持钥方能生成或校验。

- **HMAC**（RFC 2104）：`HMAC(K, m) = H((K' ⊕ opad) || H((K' ⊕ ipad) || m))`，可套在任意哈希上（TLS 1.2 的记录层 MAC 即 HMAC-SHA256 一类）；
- **CMAC**（NIST SP 800-38B）：基于分组密码的 MAC，AES-CMAC 用于企业无线 802.11i 的某些路径；
- **GMAC**：GCM 去掉加密只留认证，适合只求完整性不求机密的场景。

**MAC 与数字签名的分工**是密码学最常被混淆的一组：MAC 的生成和校验用同一把密钥，无法向第三方证明"是谁生成的"——收发双方都能造出同一条 MAC；签名用私钥签、公钥验，才具备不可抵赖性（non-repudiation，见 [Security](/docs/CS/CN/Security.md) 的安全属性一节）。两方点对点场景用 MAC 足够（更快更短），多方/审计场景必须用签名。

## Public-Key Cryptography

非对称密码的种子是两个数论难题：大整数分解（RSA 的基础）与离散对数（DH/ECDSA 的基础）。两个根问题量子计算机上都归 Shor 算法管，这是后量子迁移的全部动机（见后文）。

| 原语 | 代表算法 | 用途 | 现状 |
| :--- | :--- | :--- | :--- |
| 加密/密钥封装 | RSA-OAEP | 传输少量数据（如加密对称密钥） | 因无前向保密，TLS 1.3 已移除静态 RSA 密钥交换 |
| 密钥交换 | DH / ECDH / X25519 | 双方协商共享密钥 | X25519（RFC 7748）是现代默认；TLS 1.3 只保留 (EC)DHE |
| 签名 | RSA-PSS、ECDSA、EdDSA | 身份认证、证书、代码签名 | FIPS 186-5（2023-02）起 DSA 退出、EdDSA 进入；RSA 签名推荐 PSS 填充，PKCS#1 v1.5 遗留 |
| 抗量子 | ML-KEM、ML-DSA、SLH-DSA | 密钥封装与签名 | FIPS 203/204/205，2024-08 成为正式标准 |

两个反复翻车的实现细节：

- **RSA 填充**：PKCS#1 v1.5 填充的加密用途已被 Bleichenbacher 类自适应选择密文攻击反复击穿（ROBOT 等），新实现必须用 OAEP；签名用途推荐 PSS。
- **ECDSA 的随机数 k**：k 必须是每次签名全新的机密随机数；重用或可预测的 k 会直接泄漏私钥（PlayStation 3 被破解即此因）。EdDSA（Ed25519，RFC 8032）把 nonce 派生自闭钥与消息，从设计上消灭了这类事故。

## Key Derivation and Randomness

密码协议里真正拿来加密的密钥极少是原始口令，中间都要过 KDF（key derivation function）：

| 目标 | 工具 | 要点 |
| :--- | :--- | :--- |
| 从口令派生密钥 | PBKDF2（RFC 8018）、Argon2（RFC 9106）、bcrypt、scrypt | 必须慢且带盐；Argon2 是 2015 年密码哈希竞赛冠军，抗 GPU/ASIC 设计 |
| 从高熵材料派生会话密钥 | HKDF（RFC 5869） | extract + expand 两段；TLS 1.3 的 key schedule 就是它的变体 |
| 口令存储 | 同上一行，但目标相反 | 存储的是"慢哈希"而非密钥本身；被拖库后攻击者仍要逐条爆破 |

随机数是整套体系的地基，也是最常被低估的一环：IV、nonce、盐、会话密钥、ECDSA 的 k 都来自它。**内核 CSPRNG（`getrandom(2)` / `/dev/urandom`）初始化后即可安全使用**，"urandom 不如 random"是过时说法；真正的风险在应用层：自己用时间戳种子造随机数、复用 nonce、或从熵不足的嵌入式源取密钥——这些不是理论问题，而是历史上大量真实漏洞的直接成因。

## Digital Signatures

签名是三件套的合流：哈希（压缩）+ 私钥（绑定身份）+ 可公开验证（公钥）。协议中的典型用法：

- **证书**：CA 用私钥给"域名 + 公钥"签名，浏览器用 CA 公钥验——整个 [PKI](/docs/CS/CN/CyberSecurity/PKI.md) 信任体系就架在签名上；
- **握手认证**：TLS 1.3 的 CertificateVerify、SSH 的主机密钥、WPA3-Enterprise 的 EAP-TLS，都是签名在证明"我是我"；
- **软件供应链**：代码签名、容器镜像签名、OTA 固件签名——OWASP Top 10 2025 把供应链（A03）与完整性失效（A08）单列，正是因为签名链断裂的后果是全网级投毒。

签名算法的选择已是"收缩期"：ECDSA P-256 与 Ed25519 是当前默认；RSA-2048 仍广泛存在于旧证书；SHA-1 签名被标准禁用；后量子签名（ML-DSA）正在进入，但体积代价显著（见下节）。

## Post-Quantum Cryptography

量子威胁只精确打击非对称部分：Shor 算法破解 RSA/DH/ECDSA，Grover 算法把对称密钥搜索折半（AES-256 仍是 128 bit 量子安全强度，**对称与哈希不受影响**）。NIST 的后量子标准（2026-10 核实）：

| 标准 | 算法 | 用途 | 状态 |
| :--- | :--- | :--- | :--- |
| FIPS 203 | ML-KEM（CRYSTALS-Kyber） | 密钥封装 | 2024-08-13 发布 |
| FIPS 204 | ML-DSA（CRYSTALS-Dilithium） | 数字签名 | 2024-08-13 发布 |
| FIPS 205 | SLH-DSA（SPHINCS+） | 哈希基签名（保守备份） | 2024-08-13 发布 |
| FIPS 206 | FN-DSA（Falcon） | 小签名尺寸签名 | 草案推进中 |
| — | HQC | 码基 KEM，ML-KEM 的算法多样性备份 | 2025-03-11 入选标准化 |

迁移时间表（NIST IR 8547 初始公开草案，2024-11）：112 bit 安全强度的 RSA/ECDSA 等 **2030 年后弃用、2035 年后禁用**；≥128 bit 强度的全部 **2035 年后禁用**；配合 NSM-10 的"2035 年前完成联邦系统迁移"目标。2026-06 的两份行政令（EO-14412/14413）进一步把迁移变成带期限的政府强制要求。

**当下的工程答案是混合（hybrid）**：经典算法与 PQC 算法并联，任一被破都不致命。TLS 侧 IETF 已将混合密钥交换标准化（X25519MLKEM768 等命名组，2026-08），OpenSSL 3.5+、Go 1.24+、Chrome 131+、Firefox 132+、Safari 26+ 均默认启用，是互联网上部署最广的后量子密码。代价在握手体积：ML-KEM-768 的公钥 1184 字节，加上 X25519 的 32 字节，ClientHello 的 key share 达 1216 字节、可能跨多个 TCP 段——Cloudflare 实测约 0.34% 的源站过不了这一关（老旧中间盒问题）。

> [!WARNING]
>
> **Harvest now, decrypt later**：对保密期超过十年的数据（医疗、政务、商业机密），攻击者今天就可以存下密文，等量子计算机成熟再解。这类流量迁移到混合密钥交换没有"等标准更成熟"的余地——这正是 Cloudflare、Google、Microsoft 在 2026 年集体提前 PQC 时间表的原因。

证书侧的后量子更慢：ML-DSA-44 的公钥 1312 字节（RSA-2048 是 256 字节），一条 TLS 握手塞进整条证书链会突破 10 KB，Cloudflare 研究称届时相当比例的连接会直接失败。Let's Encrypt 已选定的解法是 Merkle Tree Certificates（MTC，批量签名 + 包含证明），staging 2026 年底、生产 2027——路线细节见 [PKI](/docs/CS/CN/CyberSecurity/PKI.md)。

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [Security](/docs/CS/CN/Security.md)
- [HTTPS](/docs/CS/CN/HTTP/HTTPS.md)
- [nginx tls](/docs/CS/CN/nginx/tls.md)
- [Wireless Security](/docs/CS/CN/CyberSecurity/Wireless_Security.md)

## References

1. [FIPS 197 - Advanced Encryption Standard (AES)](https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.197-upd1.pdf)
2. [FIPS 202 - SHA-3 Standard: Permutation-Based Hash and Extendable-Output Functions](https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.202.pdf)
3. [FIPS 203 - Module-Lattice-Based Key-Encapsulation Mechanism Standard](https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.203.pdf)
4. [RFC 8032 - Edwards-Curve Digital Signature Algorithm (EdDSA)](https://datatracker.ietf.org/doc/html/rfc8032)
5. [RFC 8439 - ChaCha20 and Poly1305 for IETF Protocols](https://datatracker.ietf.org/doc/html/rfc8439)
6. [RFC 9106 - Argon2 Memory-Hard Function for Password Hashing and Proof-of-Work Applications](https://datatracker.ietf.org/doc/html/rfc9106)
7. [NIST IR 8547 (Initial Public Draft) - Transition to Post-Quantum Cryptography Standards](https://csrc.nist.gov/pubs/ir/8547/ipd)
8. [Cloudflare Radar - Post-Quantum Encryption](https://radar.cloudflare.com/adoption-and-usage)
