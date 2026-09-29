## Introduction

LangGraph是一个低级编排框架和运行时，用于构建、管理和部署长时间运行的有状态代理

LangGraph为任何长时间运行的有状态工作流或代理提供低级支持基础设施。LangGraph不抽象提示或架构，并提供以下核心优势：

- 持久执行：构建能够在故障中持久存在并可以长时间运行的代理，从停止的地方继续执行。
- 人机协作：通过在任何点检查和修改代理状态来纳入人工监督。
- 全面的记忆：创建具有短期工作记忆（用于持续推理）和跨会话长期记忆的有状态代理。
- 使用LangSmith进行调试：通过可视化工具深入了解复杂的代理行为，这些工具可以跟踪执行路径、捕获状态转换并提供详细的运行时指标。
- 生产就绪的部署：使用专为处理有状态、长时间运行的工作流的独特挑战而设计的可扩展基础设施，自信地部署复杂的代理系统

## Installation

```shell
uv add langgraph
```



```python
from langgraph.graph import StateGraph, MessagesState, START, END

def mock_llm(state: MessagesState):
    return {"messages": [{"role": "ai", "content": "hello world"}]}

graph = StateGraph(MessagesState)
graph.add_node(mock_llm)
graph.add_edge(START, "mock_llm")
graph.add_edge("mock_llm", END)
graph = graph.compile()

graph.invoke({"messages": [{"role": "user", "content": "hi!"}]})
```






LangGraph 的本质是将工作流抽象为图（Graph），以下三个核心概念：
State（状态）：这是图的“记忆”。它是一个字典（或 Pydantic 模型），在节点之间传递。每个节点读取状态、处理数据，然后返回更新后的状态。
Nodes（节点）：图中的“工作者”。通常是 Python 函数，负责执行具体任务（如调用 LLM、查询数据库、执行代码等）。节点接收当前 State，返回需要更新的 State 字段。
Edges（边）：图中的“路线”。定义节点之间的流转逻辑。
普通边（Normal Edge）：A 执行完必定去 B。
条件边（Conditional Edge）：根据当前 State 的值，决定下一步去 B 还是去 C（这是实现 Agent 思考循环的关键）




<!-- tabs:start -->

##### **线性图**

```python
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

# ==========================================
# 1. 定义状态 (State)
# ==========================================
# 使用 TypedDict 定义图在运行过程中传递和保存的数据结构
class MyState(TypedDict):
    text: str          # 正在处理的文本
    step_count: int    # 记录执行了多少个节点

# ==========================================
# 2. 定义节点 (Nodes)
# ==========================================
# 节点就是普通的 Python 函数，接收当前 State，返回需要更新的 State 字段
def node_1(state: MyState):
    print("--- [节点 1] 开始执行：转换为大写 ---")
    # 读取当前状态
    current_text = state["text"]
    current_count = state["step_count"]
    
    # 处理逻辑
    new_text = current_text.upper()
    
    # 返回更新后的字段（LangGraph 会自动将这些字段合并到全局 State 中）
    return {"text": new_text, "step_count": current_count + 1}

def node_2(state: MyState):
    print("--- [节点 2] 开始执行：添加感叹号 ---")
    current_text = state["text"]
    current_count = state["step_count"]
    
    new_text = current_text + "!"
    
    return {"text": new_text, "step_count": current_count + 1}

# ==========================================
# 3. 构建图 (Graph)
# ==========================================
# 初始化图，并绑定我们定义的状态类型
workflow = StateGraph(MyState)

# 添加节点（给节点起个名字，并绑定对应的函数）
workflow.add_node("uppercase_node", node_1)
workflow.add_node("exclaim_node", node_2)

# 添加边（定义节点之间的流转路线）
workflow.add_edge(START, "uppercase_node")       # 起点 -> 节点1
workflow.add_edge("uppercase_node", "exclaim_node") # 节点1 -> 节点2
workflow.add_edge("exclaim_node", END)           # 节点2 -> 终点

# ==========================================
# 4. 编译与运行
# ==========================================
# 编译图，生成可运行的应用
app = workflow.compile()

if __name__ == "__main__":
    # 定义初始输入状态
    initial_state = {
        "text": "hello langgraph", 
        "step_count": 0
    }
    
    print(f"🚀 初始状态: {initial_state}\n")
    
    # 运行图 (invoke 会同步执行并返回最终结果)
    final_state = app.invoke(initial_state)
    
    print(f"\n✅ 最终状态: {final_state}")
```


##### **条件**

```python
from typing import TypedDict, Literal
from langgraph.graph import StateGraph, START, END

# ==========================================
# 1. 定义状态 (State)
# ==========================================
class GraphState(TypedDict):
    text: str               # 待分类的文本
    category: str           # 分类结果 (如: "positive", "negative", "unknown")
    retry_count: int        # 重试次数（用于控制循环和模拟逻辑）

# ==========================================
# 2. 定义节点 (Nodes)
# ==========================================
def classify_node(state: GraphState):
    """模拟分类器：前两次故意失败，第三次成功"""
    print(f"🧠 [分类节点] 正在分析文本: '{state['text']}' (第 {state['retry_count'] + 1} 次尝试)")
    
    # 模拟 LLM 的不稳定性：前两次返回 unknown
    if state["retry_count"] < 2:
        print("   -> 结果: 置信度太低，分类失败 (unknown)")
        return {"category": "unknown"}
    else:
        print("   -> 结果: 分类成功！(positive)")
        return {"category": "positive"}

def refine_node(state: GraphState):
    """模拟修正器：调整策略，准备重试"""
    print(f"🔧 [修正节点] 分类失败。正在优化提示词/重新检查数据...")
    # 增加重试次数，这是触发循环结束的关键
    return {"retry_count": state["retry_count"] + 1}

# ==========================================
# 3. 定义条件路由 (Conditional Routing)
# ==========================================
def route_classification(state: GraphState) -> Literal["refine", "end"]:
    """
    根据分类结果决定下一步去哪。
    返回值必须是我们在 add_conditional_edges 中定义的映射键。
    """
    if state["category"] == "unknown":
        return "refine"  # 失败 -> 去修正节点
    else:
        return "end"     # 成功 -> 结束

# ==========================================
# 4. 构建图 (Graph)
# ==========================================
workflow = StateGraph(GraphState)

# 添加节点
workflow.add_node("classifier", classify_node)
workflow.add_node("refiner", refine_node)

# 添加边
workflow.add_edge(START, "classifier") # 1. 起点 -> 分类节点

# 2. 核心：添加条件边 (从分类节点出发)
# 我们传入路由函数，并定义返回值到目标节点的映射
workflow.add_conditional_edges(
    "classifier",               # 源节点
    route_classification,       # 路由函数
    {
        "refine": "refiner",    # 如果路由函数返回 "refine"，则走向 "refiner" 节点
        "end": END              # 如果路由函数返回 "end"，则走向 END 节点
    }
)

# 3. 形成循环：修正节点 -> 分类节点
workflow.add_edge("refiner", "classifier") 

# ==========================================
# 5. 编译与运行
# ==========================================
app = workflow.compile()

if __name__ == "__main__":
    initial_state = {
        "text": "LangGraph is absolutely amazing!", 
        "category": "", 
        "retry_count": 0
    }
    
    print("🚀 开始运行带有循环的分类器...\n" + "="*40)
    
    # 运行图
    final_state = app.invoke(initial_state)
    
    print("="*40 + "\n")
    print(f"✅ 最终结果: 文本 '{final_state['text']}' 被分类为 -> [{final_state['category']}]")
    print(f"🔄 总共重试了 {final_state['retry_count']} 次。")
```

<!-- tabs:end -->


接下来引入 LLM，

前提

```shell
pip install --upgrade langgraph langchain-openai langchain-core
```

<!-- tabs:start -->

##### **ReAct**

```py
import os
from typing import Literal
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode

# ==========================================
# 0. 配置 DeepSeek 模型
# ==========================================
# DeepSeek 兼容 OpenAI 接口，所以用 ChatOpenAI 即可
llm = ChatOpenAI(
    model="deepseek-chat",  # 推荐使用 deepseek-chat (V3)
    api_key="your-deepseek-api-key", # 替换为你的 API Key
    base_url="https://api.deepseek.com",
    temperature=0.1 # Agent 场景建议降低 temperature 以提高稳定性
)

# ==========================================
# 1. 定义工具 (Tools)
# ==========================================
@tool
def get_current_weather(city: str) -> str:
    """获取指定城市的当前天气情况。"""
    # 模拟天气 API 返回
    weather_data = {
        "北京": "晴天，25°C",
        "上海": "多云，22°C",
        "广州": "小雨，28°C"
    }
    return weather_data.get(city, f"抱歉，找不到 {city} 的天气数据。")

@tool
def calculate_math(expression: str) -> str:
    """计算数学表达式，例如 '2 + 2' 或 '10 * 5'。"""
    try:
        # 注意：实际生产中 eval 有安全风险，这里仅为演示
        result = eval(expression) 
        return f"计算结果是: {result}"
    except Exception as e:
        return f"计算出错: {str(e)}"

# 将工具列表绑定到 LLM 上
tools = [get_current_weather, calculate_math]
llm_with_tools = llm.bind_tools(tools)

# ==========================================
# 2. 定义节点 (Nodes)
# ==========================================
# 节点 1: Agent 思考节点
def agent_node(state: MessagesState):
    """
    Agent 节点：接收消息历史，调用 LLM，并返回 LLM 的响应。
    MessagesState 会自动将返回的 messages 追加到历史中。
    """
    print("🧠 [Agent] 正在思考...")
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}

# 节点 2: 工具执行节点 (使用 LangGraph 官方预构建的 ToolNode)
# ToolNode 会自动解析 LLM 的 tool_calls，执行对应的工具，并将结果作为 ToolMessage 返回
tool_node = ToolNode(tools)

# ==========================================
# 3. 定义条件路由 (Conditional Routing)
# ==========================================
def should_continue(state: MessagesState) -> Literal["tools", "end"]:
    """
    路由函数：判断 Agent 的响应是否包含工具调用。
    如果包含，去执行工具；如果不包含（直接回答），则结束。
    """
    last_message = state["messages"][-1]
    # 检查最后一条消息是否有 tool_calls 属性且不为空
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        print("🛠️ [路由] 决定调用工具...")
        return "tools"
    else:
        print("🏁 [路由] 决定结束对话...")
        return "end"

# ==========================================
# 4. 构建图 (Graph)
# ==========================================
# 使用官方推荐的 MessagesState，它内置了消息追加的 Reducer
workflow = StateGraph(MessagesState)

# 添加节点
workflow.add_node("agent", agent_node)
workflow.add_node("tools", tool_node)

# 添加边
workflow.add_edge(START, "agent") # 入口 -> Agent

# 添加条件边 (Agent -> 工具 或 结束)
workflow.add_conditional_edges(
    "agent",
    should_continue,
    {
        "tools": "tools", # 如果返回 "tools"，走向 "tools" 节点
        "end": END        # 如果返回 "end"，走向 END 节点
    }
)

# 添加普通边，形成循环 (工具执行完 -> 回到 Agent 继续思考)
workflow.add_edge("tools", "agent")

# 编译图
app = workflow.compile()

# ==========================================
# 5. 运行测试
# ==========================================
if __name__ == "__main__":
    print("="*50)
    print("🚀 启动 DeepSeek ReAct Agent")
    print("="*50)
    
    # 测试用例 1：需要调用天气工具
    query1 = "北京今天天气怎么样？顺便帮我算一下 123 乘以 456 等于多少。"
    print(f"\n👤 用户提问: {query1}\n")
    
    # invoke 会同步运行整个图，直到遇到 END
    final_state = app.invoke({"messages": [("user", query1)]})
    
    # 提取最终 AI 的回答 (最后一条消息的内容)
    final_answer = final_state["messages"][-1].content
    print(f"\n🤖 Agent 最终回答:\n{final_answer}")
    
    print("\n" + "="*50)
```


##### **流式输出**

```py
import os
from typing import Literal
from langchain_core.tools import tool
from langchain_core.messages import AIMessageChunk, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode

# ==========================================
# 0. 配置 DeepSeek 模型
# ==========================================
llm = ChatOpenAI(
    model="deepseek-chat",
    api_key="your-deepseek-api-key", # 替换为你的 API Key
    base_url="https://api.deepseek.com",
    temperature=0.1,
    streaming=True # 显式开启流式（虽然 stream_mode 会处理，但加上更保险）
)

# ==========================================
# 1. 定义工具 (Tools)
# ==========================================
@tool
def get_current_weather(city: str) -> str:
    """获取指定城市的当前天气情况。"""
    import time
    time.sleep(1) # 模拟网络延迟，让你更明显地看到流式效果
    weather_data = {"北京": "晴天，25°C", "上海": "多云，22°C"}
    return weather_data.get(city, f"抱歉，找不到 {city} 的天气数据。")

@tool
def calculate_math(expression: str) -> str:
    """计算数学表达式。"""
    try:
        return f"计算结果是: {eval(expression)}"
    except Exception as e:
        return f"计算出错: {str(e)}"

tools = [get_current_weather, calculate_math]
llm_with_tools = llm.bind_tools(tools)

# ==========================================
# 2. 定义节点 (Nodes)
# ==========================================
def agent_node(state: MessagesState):
    return {"messages": [llm_with_tools.invoke(state["messages"])]}

tool_node = ToolNode(tools)

# ==========================================
# 3. 定义条件路由 (Conditional Routing)
# ==========================================
def should_continue(state: MessagesState) -> Literal["tools", "end"]:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "end"

# ==========================================
# 4. 构建图 (Graph) - 与之前完全一致
# ==========================================
workflow = StateGraph(MessagesState)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", tool_node)

workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
workflow.add_edge("tools", "agent")

app = workflow.compile()

# ==========================================
# 5. 🌟 核心修改：流式运行与终端展示 🌟
# ==========================================
if __name__ == "__main__":
    print("="*60)
    print("🚀 启动 DeepSeek ReAct Agent (流式输出版)")
    print("="*60)
    
    query = "北京今天天气怎么样？顺便帮我算一下 123 乘以 456 等于多少。"
    print(f"\n👤 用户提问: {query}\n")
    print("🤖 Agent 回答: ", end="") # 提前打印前缀
    
    # 使用 stream 方法，并指定 stream_mode="messages"
    # 它会 yield 两个值：(message_chunk, metadata)
    for chunk, metadata in app.stream(
        {"messages": [("user", query)]}, 
        stream_mode="messages"
    ):
        # 获取当前 chunk 是由哪个节点产生的
        node_name = metadata.get("langgraph_node", "")
        
        # 1. 处理 Agent 节点产生的文本流 (实现打字机效果)
        if node_name == "agent" and isinstance(chunk, AIMessageChunk):
            # 过滤掉空内容，实时打印到终端
            if chunk.content:
                print(chunk.content, end="", flush=True)
                
        # 2. 处理工具节点产生的结果 (让工具调用过程可视化)
        elif node_name == "tools" and isinstance(chunk, ToolMessage):
            # 换行打印工具结果，避免和 Agent 的文本混在一起
            print(f"\n\n🛠️ [工具执行结果]: {chunk.content}")
            print("🤖 Agent 继续思考: ", end="") # 打印提示，表示 Agent 拿到结果继续说了

    print("\n\n" + "="*60)
    print("✅ 对话结束！")
```



##### **多轮对话**


在 LangGraph 中，实现记忆的核心机制叫做 Checkpointing（检查点/状态持久化）。它的工作原理是：在图的每一步执行后，将当前的 State（状态）保存起来。当你开启新一轮对话时，只要提供相同的“会话 ID”，LangGraph 就会自动加载上一次的 State，从而实现记忆。



```py
import os
from typing import Literal
from langchain_core.tools import tool
from langchain_core.messages import AIMessageChunk, ToolMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode
# 🌟 新增导入：内存检查点 (用于实现多轮记忆)
from langgraph.checkpoint.memory import MemorySaver 

# ==========================================
# 0. 配置 DeepSeek 模型
# ==========================================
llm = ChatOpenAI(
    model="deepseek-chat",
    api_key="your-deepseek-api-key", 
    base_url="https://api.deepseek.com",
    temperature=0.1,
    streaming=True
)

# ==========================================
# 1. 定义工具 (Tools)
# ==========================================
@tool
def get_current_weather(city: str) -> str:
    """获取指定城市的当前天气情况。"""
    weather_data = {"北京": "晴天，25°C", "上海": "多云，22°C", "广州": "小雨，28°C"}
    return weather_data.get(city, f"抱歉，找不到 {city} 的天气数据。")

tools = [get_current_weather]
llm_with_tools = llm.bind_tools(tools)

# ==========================================
# 2. 定义节点 (Nodes)
# ==========================================
def agent_node(state: MessagesState):
    return {"messages": [llm_with_tools.invoke(state["messages"])]}

tool_node = ToolNode(tools)

# ==========================================
# 3. 定义条件路由 (Conditional Routing)
# ==========================================
def should_continue(state: MessagesState) -> Literal["tools", "end"]:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "end"

# ==========================================
# 4. 构建图 (Graph)
# ==========================================
workflow = StateGraph(MessagesState)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", tool_node)

workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
workflow.add_edge("tools", "agent")

# 🌟 核心修改 1：实例化 MemorySaver
memory = MemorySaver()

# 🌟 核心修改 2：编译时传入 checkpointer
app = workflow.compile(checkpointer=memory)

# ==========================================
# 5. 🌟 多轮对话交互循环 🌟
# ==========================================
if __name__ == "__main__":
    print("="*60)
    print("🚀 启动 DeepSeek ReAct Agent (流式 + 多轮记忆版)")
    print("💡 提示：输入 'exit' 或 'quit' 退出程序。")
    print("="*60)
    
    # 🌟 核心修改 3：定义配置，包含 thread_id
    # 这个 thread_id 决定了对话的上下文。你可以把它想象成微信的“聊天窗口 ID”
    thread_id = "user_session_001" 
    config = {"configurable": {"thread_id": thread_id}}
    
    while True:
        try:
            # 获取用户输入
            user_input = input("\n👤 你: ").strip()
            
            if user_input.lower() in ['exit', 'quit', '退出']:
                print("👋 再见！")
                break
                
            if not user_input:
                continue
                
            print("\n🤖 Agent: ", end="")
            
            # 🌟 核心修改 4：运行图时传入 config
            for chunk, metadata in app.stream(
                {"messages": [HumanMessage(content=user_input)]}, 
                config=config,  # 传入包含 thread_id 的配置
                stream_mode="messages"
            ):
                node_name = metadata.get("langgraph_node", "")
                
                # 处理 Agent 文本流
                if node_name == "agent" and isinstance(chunk, AIMessageChunk):
                    if chunk.content:
                        print(chunk.content, end="", flush=True)
                        
                # 处理工具节点结果
                elif node_name == "tools" and isinstance(chunk, ToolMessage):
                    print(f"\n\n🛠️ [工具执行结果]: {chunk.content}")
                    print("🤖 Agent: ", end="")
                    
            print() # 换行，让下一次输入更美观
            
        except KeyboardInterrupt:
            print("\n\n👋 强制退出。")
            break
        except Exception as e:
            print(f"\n❌ 发生错误: {e}")
```

##### **人工介入**

```py

```


<!-- tabs:end -->


## Links





## References

1. [LangGraph中文文档](https://langchain-doc.cn/v1/python/langgraph/overview.html)

