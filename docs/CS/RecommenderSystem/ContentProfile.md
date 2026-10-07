## Introduction

推荐内容与场景通常可以分为以下几类，根据所推荐的内容不同，其内容画像的处理方式也不同。除了内容本身，用户所处的**环境**同样是重要的画像输入。

## Content Profile

- 文章推荐：例如新闻内容推荐，需要利用 [NLP](/docs/CS/AI/NLP/NLP.md) 的技术对文章的标题，正文等提取关键词、标签、分类等。
- 视频推荐：除了对于分类、标题关键词的抓取外，还依赖于图片与视频处理技术，例如识别内容标签、内容相似性等（图像侧的模型基础见 [CNN](/docs/CS/AI/CNN.md)）。

## Environment Variables

内容画像外，环境画像也非常重要。

例如在短视频的推荐场景中，用户在看到一条视频所处的时间、地点以及当时所浏览的前后内容、当天已浏览时间等也是非常重要的信息，但由于环境变量数据量较大、类型较多，对推荐架构以及工程实现能力的要求也较高。

## Processing Pipeline

一条内容从入库到可被召回，通常经过五步，每步的产物服务不同的下游：

1. **清洗与归一**：去模板文本、乱码、重复空白；正文与标题分离；多语言与繁简归一
2. **词级表示**：分词与关键词抽取，产出可枚举的词条
3. **结构与实体**：类目分类、品牌/演员/地点等实体识别、情感与标题党判定——这一步产出的是可做倒排的标签（倒排与全文检索的机制见 [ES](/docs/CS/Framework/ES/ES.md?id=inverted-index)）
4. **向量表示**：文本、图像、音频各走自己的编码器（图像侧见 [CNN](/docs/CS/AI/CNN.md)，语义 embedding 见 [NLP](/docs/CS/AI/NLP/NLP.md)），拼成内容向量，供相似召回与去重
5. **入索引**：标签进倒排、向量进 ANN 索引、约束字段（在架、时效、地域）进过滤器——三者的更新延迟决定了新内容多久能被推出去（索引侧细节见 [Recall](/docs/CS/RecommenderSystem/Recall.md)）

第 2 步最常用的基线是 TF-IDF：一个词在单篇里出现得越多权重越大，但在全集里越普遍则被压得越低：

$$
\mathrm{tfidf}(t, d) = \mathrm{tf}(t, d) \cdot \log \frac{N}{1 + \mathrm{df}(t)}
$$

分母加 1 是对未出现词的平滑，各家实现（如 sklearn）还有一系列变体，换实现就会换数值，所以口径必须固定并记录。另一条路线是基于词图共现的图算法（TextRank 一类），它不依赖语料全集统计，因此更适合短文本与新入库内容。

## Quality and Lifecycle

内容画像不只是"它是什么"，还包括"它此刻值不值得推"：

- **质量分**：低质识别（搬运、拼凑、诱导点击）与人工审核标签。质量分常被当成排序的乘法因子或过滤门槛，但它同时是最容易被刷的一方
- **重复与近重复**：同一事件的海量转载要聚类去重，否则一屏全是同一内容。做法是向量近邻 + 阈值聚类
- **时效性**：新闻以小时计、教程以月计。时效标签要参与过滤（过期硬下架），而不是只作为降权特征
- **反馈闭环的污染**：内容质量分若由 CTR 反推，就会与"标题党"共谋——高点击低完读的内容应当被识别，这需要把**后验行为（完播、负反馈）**而非点击纳入质量建模（偏差机制见 [Evaluation](/docs/CS/RecommenderSystem/Evaluation.md)）

## Division of Labor with User Profiles

两者看似对称，实际差别很大：内容画像可以**由供给侧直接给定**（作者填的类目、平台打的标），相对稳定且可核对；用户画像只能**从行为推断**，永远带着置信度问题。因此冷启动阶段内容画像是唯一可用的依据，而成熟期它的主要角色退化为精排模型的一路特征来源，同时承担"新物品如何进候选池"的职责。

## Division of Labor with Collaborative Filtering

内容画像的价值在**冷启动**：新物品还没有交互记录，协同过滤无从下手（见 [CollaborativeFiltering](/docs/CS/RecommenderSystem/CollaborativeFiltering.md) 的 Cold Start and Long Tail），只能靠标签与向量把物品推进候选集。等到行为数据积累起来，CF 会反过来接管主要召回路，内容特征则退居为精排模型里的一路输入。两者不是替代关系，而是同一个物品在生命周期不同阶段的主导依据不同。

## Links

- [推荐系统](/docs/CS/RecommenderSystem/RecommenderSystem.md)
- [Scenario](/docs/CS/RecommenderSystem/Scenario.md)
- [UserProfile](/docs/CS/RecommenderSystem/UserProfile.md)
- [CollaborativeFiltering](/docs/CS/RecommenderSystem/CollaborativeFiltering.md)
- [Recall](/docs/CS/RecommenderSystem/Recall.md)
- [Pipeline](/docs/CS/RecommenderSystem/Pipeline.md)
- [NLP](/docs/CS/AI/NLP/NLP.md)
- [CNN](/docs/CS/AI/CNN.md)
- [ES](/docs/CS/Framework/ES/ES.md)

## References

1. [从零开始了解推荐系统全貌-微信公众号](https://mp.weixin.qq.com/s/n1PB5LGppaxlfRWx8WxhLg)
1. [TfidfVectorizer 文档-scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html)
1. [推荐系统实践-豆瓣](https://book.douban.com/subject/10769749/)
