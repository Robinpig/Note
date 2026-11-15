## Introduction

[Chunk](/docs/CS/Distributed/Tracing/Prometheus/Chunk.md) 讲 Prometheus TSDB 的样本压缩编码：XOR chunk 的 Gorilla 时间戳 delta-of-delta、浮点值 leading/trailing XOR，原生直方图的 varbit 编码，以及 v3.16 新增的 XOR2/ST 编码族。TSDB 每 sample 平均 ~1.37 字节的压缩率全部来自这里。

> [!NOTE]
> 源码级笔记。代码事实基于 `prometheus/prometheus` **v3.16.0**（commit `e2e28adeee2c5883d000fc82aca6008cfbf7e96d`）。讲解直接贴真实源码，路径相对仓库根，不再标注行号。

## 编码族一览

```go
// tsdb/chunkenc/chunk.go
// The different available chunk encodings.
const (
	EncNone Encoding = iota
	EncXOR
	EncHistogram
	EncFloatHistogram
	EncXOR2
	EncHistogramST
	EncFloatHistogramST
)
```

`EncXOR` 是经典 Gorilla 编码；`EncXOR2` 及 `EncHistogramST`/`EncFloatHistogramST` 是 v3.16 引入的支持 ST（start timestamp）的变体，为乱序样本（OOO）在 chunk 内携带每样本起始时间。尺寸红线：

```go
// tsdb/chunkenc/chunk.go
const (
	// MaxBytesPerXORChunk is the maximum size an XOR chunk can be.
	MaxBytesPerXORChunk = 1024
	// MaxBytesPerXORChunkBeforeAppend is used for cutting new XOR chunks, to prevent going over MaxBytesPerXORChunk
	// as a hard limit. We assume the next sample will be a maximally-sized sample (19 bytes).
	MaxBytesPerXORChunkBeforeAppend = MaxBytesPerXORChunk - 19
	// TargetBytesPerHistogramChunk sets a size target for each histogram chunk.
	TargetBytesPerHistogramChunk = 1024
	// MinSamplesPerHistogramChunk sets a minimum sample count for histogram chunks. ...
	MinSamplesPerHistogramChunk = 10
)
```

`MaxBytesPerXORChunk - 19` 这个数字值得停留：XOR chunk 里单样本最坏 19 字节，切 chunk 前预留一个最坏样本的空间，保证追加时不会硬性超限。1024 字节 + 默认 2 小时窗口，就是「每 chunk 约 120 个样本」的来源。

## bstream：位流

所有编码都压在同一个位级容器 `bstream` 上——写入按 bit 对齐，不按字节：

```go
// tsdb/chunkenc/bstream.go
type bstream struct {
	stream []byte // the data stream
	count  uint8  // how many bits are free in the last byte
}

func (b *bstream) writeBit(bit bit) {
	if b.count == 0 {
		b.stream = append(b.stream, 0)
		b.count = 8
	}
	// ...
}
```

XOR chunk 前 2 字节是头部：样本数（uint16 big-endian）+ 编码标记。迭代器构造时会显式跳过头部：

```go
// tsdb/chunkenc/xor.go — XORChunk.iterator
	return &xorIterator{
		// The first 2 bytes contain chunk headers.
		// We skip that for actual samples.
		br:       newBReader(c.b.bytes()[chunkHeaderSize:]),
		numTotal: binary.BigEndian.Uint16(c.b.bytes()),
		t:        math.MinInt64,
	}
```

## Gorilla 时间戳编码

`xorAppender.Append` 的三分支就是 Gorilla 论文的完整实现：首样本全量 varint 时间戳 + 64bit 值；第二样本 uvarint delta；之后全部用 delta-of-delta：

```go
// tsdb/chunkenc/xor.go — xorAppender.Append
func (a *xorAppender) Append(_, t int64, v float64) {
	var tDelta uint64
	num := binary.BigEndian.Uint16(a.b.bytes())
	switch num {
	case 0:
		buf := make([]byte, binary.MaxVarintLen64)
		for _, b := range buf[:binary.PutVarint(buf, t)] {
			a.b.writeByte(b)
		}
		a.b.writeBits(math.Float64bits(v), 64)
	case 1:
		tDelta = uint64(t - a.t)

		buf := make([]byte, binary.MaxVarintLen64)
		for _, b := range buf[:binary.PutUvarint(buf, tDelta)] {
			a.b.writeByte(b)
		}

		a.writeVDelta(v)
	case math.MaxUint16:
		panic("chunk capacity exceeded")
	default:
		tDelta = uint64(t - a.t)
		dod := int64(tDelta - a.tDelta)

		// Gorilla has a max resolution of seconds, Prometheus milliseconds.
		// Thus we use higher value range steps with larger bit size.
```

dod 桶宽是 Prometheus 对 Gorilla 的适配改动——Gorilla 秒级精度下 dod 桶是 7/9/12 bits，Prometheus 毫秒精度放大为 14/17/20 bits：

```go
// tsdb/chunkenc/xor.go — xorAppender.Append (续)
		switch {
		case dod == 0:
			a.b.writeBit(zero)
		case bitRange(dod, 14):
			a.b.writeByte(0b10<<6 | (uint8(dod>>8) & (1<<6 - 1))) // 0b10 size code combined with 6 bits of dod.
			a.b.writeByte(uint8(dod))                             // Bottom 8 bits of dod.
		case bitRange(dod, 17):
			a.b.writeBits(0b110, 3)
			a.b.writeBits(uint64(dod), 17)
		case bitRange(dod, 20):
			a.b.writeBits(0b1110, 4)
			a.b.writeBits(uint64(dod), 20)
		default:
			a.b.writeBits(0b1111, 4)
			a.b.writeBits(uint64(dod), 64)
		}

		a.writeVDelta(v)
	}

	a.t = t
	a.v = v
	binary.BigEndian.PutUint16(a.b.bytes(), num+1)
	a.tDelta = tDelta
}
```

等间隔抓取下 dod 恒为 0，每样本时间戳只花 **1 bit**——这是「`scrape_interval` 固定时存储成本骤降」的编码层原因。

## 浮点值 XOR

值编码是经典的 leading/trailing 压缩：与上一个值异或后，只存有效位窗口。窗口命中上一次的区间时只花 1 bit 前缀：

```go
// tsdb/chunkenc/xor.go
func xorWrite(b *bstream, newValue, currentValue float64, leading, trailing *uint8) {
	delta := math.Float64bits(newValue) ^ math.Float64bits(currentValue)

	if delta == 0 {
		b.writeBit(zero)
		return
	}
	b.writeBit(one)

	newLeading := uint8(bits.LeadingZeros64(delta))
	newTrailing := uint8(bits.TrailingZeros64(delta))

	// Clamp number of leading zeros to avoid overflow when encoding.
	if newLeading >= 32 {
		newLeading = 31
	}

	if *leading != 0xff && newLeading >= *leading && newTrailing >= *trailing {
		// In this case, we stick with the current leading/trailing.
		b.writeBit(zero)
		b.writeBits(delta>>*trailing, 64-int(*leading)-int(*trailing))
		return
	}

	// Update leading/trailing for the caller.
	*leading, *trailing = newLeading, newTrailing

	b.writeBit(one)
	b.writeBits(uint64(newLeading), 5)

	// Note that if newLeading == newTrailing == 0, then sigbits == 64. But
	// that value doesn't actually fit into the 6 bits we have.  Luckily, we
	// never need to encode 0 significant bits, since that would put us in the
	// other case (vdelta == 0).  So instead we write out a 0 and adjust
	// it back to 64 on unpacking.
	sigbits := 64 - newLeading - newTrailing
	b.writeBits(uint64(sigbits), 6)
	b.writeBits(delta>>newTrailing, int(sigbits))
}
```

两个工程细节：leading 截到 31 防 5bit 溢出；注释解释了 sigbits=64 装不进 6bit 时为什么安全（那种情形已经走 delta==0 分支）。

## 直方图 varbit 编码

原生直方图 chunk（`EncHistogram`/`EncFloatHistogram`）不用 XOR，而是 `varbit.go` 的桶式前缀编码。整数值按大小落 10 个桶：

```go
// tsdb/chunkenc/varbit.go
func putVarbitInt(b *bstream, val int64) {
	switch {
	case val == 0: // Precisely 0, needs 1 bit.
		b.writeBit(zero)
	case bitRange(val, 3): // -3 <= val <= 4, needs 5 bits.
		b.writeBits(0b10, 2)
		b.writeBits(uint64(val), 3)
	case bitRange(val, 6): // -31 <= val <= 32, 9 bits.
		b.writeBits(0b110, 3)
		b.writeBits(uint64(val), 6)
	case bitRange(val, 9): // -255 <= val <= 256, 13 bits.
		b.writeBits(0b1110, 4)
		b.writeBits(uint64(val), 9)
	case bitRange(val, 12): // -2047 <= val <= 2048, 17 bits.
		b.writeBits(0b11110, 5)
		b.writeBits(uint64(val), 12)
	case bitRange(val, 18): // -131071 <= val <= 131072, 3 bytes.
		b.writeBits(0b111110, 6)
		b.writeBits(uint64(val), 18)
	case bitRange(val, 25): // -16777215 <= val <= 16777216, 4 bytes.
		b.writeBits(0b1111110, 7)
		b.writeBits(uint64(val), 25)
	case bitRange(val, 56): // -36028797018963967 <= val <= 36028797018963968, 8 bytes.
		b.writeBits(0b11111110, 8)
		b.writeBits(uint64(val), 56)
	default:
		b.writeBits(0b11111111, 8) // Worst case, needs 9 bytes.
		b.writeBits(uint64(val), 64)
	}
}
```

直方图计数（bucket count、count、sum 的 mantissa）随时间高度单调，varbit + 差值组合的收益与 Gorilla 同构。XOR2 路径还内置了一个 `putVarbitIntFast`——把前缀与值合并成单次 `writeBitsFast` 调用，省掉位流的逐段开销：

```go
// tsdb/chunkenc/varbit.go
// putVarbitIntFast is like putVarbitInt but combines the prefix and value into
// a single writeBitsFast call per bucket, reducing bstream overhead on the hot
// path. It is used by XOR2 encoding.
//
// TODO(XOR2): Once XOR2 is stable, merge putVarbitInt and putVarbitIntFast.
```

## Links

- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [Tsdb](/docs/CS/Distributed/Tracing/Prometheus/Tsdb.md)
- [Index](/docs/CS/Distributed/Tracing/Prometheus/Index.md)
- [Wal](/docs/CS/Distributed/Tracing/Prometheus/Wal.md)
- [Scrape](/docs/CS/Distributed/Tracing/Prometheus/Scrape.md)

## References

- https://github.com/prometheus/prometheus/blob/v3.16.0/tsdb/chunkenc/xor.go
- https://github.com/prometheus/prometheus/blob/v3.16.0/tsdb/chunkenc/varbit.go
- https://github.com/prometheus/prometheus/blob/v3.16.0/docs/bstream.md
- Gorilla: A Fast, Scalable, In-Memory Time Series Database (VLDB 2015)
