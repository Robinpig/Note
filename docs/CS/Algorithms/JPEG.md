## Introduction

JPEG（Joint Photographic Experts Group）是最经典的**有损图像压缩**标准，针对自然照片利用人眼的两类不敏感做压缩：
对颜色细节不如亮度敏感、对高频（边缘、纹理的剧烈变化）不如低频敏感。其基线（baseline）编码管线如下：

1. Color Space Conversion（色彩空间转换）
2. Chrominance Downsampling（色度下采样）
3. Discrete Cosine Transform（离散余弦变换 DCT）
4. Quantization（量化）
5. Run-Length and [Huffman](/docs/CS/Algorithms/tree/Huffman-Tree.md) Encoding（游程编码 + 熵编码）

其中第 4 步量化是**唯一的有损环节**，其余都是可精确逆运算的变换。

## Pipeline

### 1. Color Space Conversion

把 RGB 转换为 **YCbCr**：Y 是亮度（luma），Cb/Cr 是两个色度（chroma，蓝色差、红色差）。
转换是线性的、可逆的，本身不压缩数据，目的是把「明暗」与「颜色」分开，便于下一步区别对待。

### 2. Chrominance Downsampling

人眼对色度的空间分辨率不敏感，于是对 Cb、Cr 降采样（常见 4:2:0，水平和垂直各减半），两个色度通道的像素数降到约 1/4，
而亮度 Y 保持全分辨率。这一步在观看影响很小的情况下大幅减少数据。

### 3. Block Splitting and DCT

图像被切成 8×8 的块，每块减去 128（把像素值平移到以 0 为中心），再做二维**离散余弦变换（DCT）**：

- DCT 把 64 个空间域像素变换为 64 个频率系数，左上角 `[0,0]` 是 **DC 系数**（块的平均亮度），其余是 **AC 系数**；
- 系数越往右下代表越高的空间频率，而自然图像的能量集中在低频（左上），高频系数本来就接近 0；
- DCT 本身可逆、不丢信息，只是把数据搬到一个「便于按重要性取舍」的坐标系。

### 4. Quantization

用一张 8×8 的量化表逐系数做整数除法 `round(系数 / 量化步长)`：

- 高频位置给大的步长，商被舍入成 0；低频步长小、保留较精。这一步把大量高频系数变成 0，是压缩率与画质的主要调节阀；
- 质量参数（quality factor）本质是在缩放这张量化表；
- 因为做了舍入，**无法精确还原**，这就是有损的来源。

### 5. Run-Length and Entropy Coding

- 量化后的 8×8 系数按 **Zig-Zag（之字形）** 顺序扫描，使低频在前、高频在后，连续的 0 被集中到尾部；
- 对这些 0 做**游程编码（RLE）**：用「(连续 0 的个数, 下一个非零值)」表示，长串 0 被压成很少的符号；
- DC 系数在块间通常相近，先对相邻块 DC 差值编码（DPCM）；
- 最后对所有符号做**熵编码**：基线 JPEG 用 [Huffman 编码](/docs/CS/Algorithms/tree/Huffman-Tree.md)（高频符号用短码），也存在算术编码版本。

解码是逆过程：Huffman/RLE 解码 → 反 Zig-Zag → 反量化 → 逆 DCT → 上采样 → YCbCr 转回 RGB。

## Trade-offs

- 适合**照片、连续色调**图像；不适合含锐利文字、线条、Logo 的图（8×8 块边界在高压下产生可见的 ringing/块效应），这类场景用 PNG（无损）或 WebP 更好。
- 压缩率与质量由量化表（quality）权衡；多次重新保存 JPEG 会反复量化，代际损失累积。
- JPEG 只压缩**单帧静态图**；运动 JPEG（M-JPEG）是把视频逐帧独立 JPEG，不利用帧间冗余，真正的视频压缩见 H.264/HEVC（含运动估计与帧间预测）。
- 现代替代：WebP/AVIF/JPEG XL 引入更好的变换（如小波、更先进的熵编码）和 alpha 通道，压缩率更高。

## Links

- [Huffman Tree](/docs/CS/Algorithms/tree/Huffman-Tree.md) — 熵编码所用的最优前缀码
- [Algorithms](/docs/CS/Algorithms/Algorithms.md)

## References

1. [JPEG - Wikipedia](https://en.wikipedia.org/wiki/JPEG)
2. [ITU T.81 / JPEG standard](https://www.w3.org/Graphics/JPEG/itu-t81.pdf)
