import asyncio
from dotenv import load_dotenv
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from mcp import StdioServerParameters, stdio_client, ClientSession
from langchain_core.tools import tool
from langchain_mcp_adapters.tools import load_mcp_tools

load_dotenv()

@tool
def save_url(url: str, collected_urls: list) -> str:
    """保存一个职位的详情页URL到列表中。"""
    collected_urls.append(url)
    return f"已保存URL: {url}"

async def run_agent_with_custom_tool():
    collected_urls = []
    config = {"recursion_limit": 100}
    
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@playwright/mcp"]
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            mcp_tools = await load_mcp_tools(session)
            # 合并自定义工具
            all_tools = mcp_tools + [save_url]
            print(f"Loaded tools: {[tool.name for tool in all_tools]}")
            
            llm = ChatOpenAI(model="qwen3.6-flash", temperature=0)
            agent = create_react_agent(llm, all_tools)
            
            # 修改后的提示词，要求模型使用 save_url 工具
            user_query = """
目标：打开网页https://campus.kuaishou.cn/recruit/campus/e/#/campus/job-info/11269
并返回所有内容。
"""
            
            print(f"\nExecuting task: {user_query}")
            
            try:
                async for event in agent.astream_events(
                    {"messages": [("user", user_query)]},
                    config=config,
                    version="v2"
                ):
                    # 流式输出模型思考过程
                    if event["event"] == "on_chat_model_stream":
                        content = event["data"]["chunk"].content
                        if content:
                            print(content, end="", flush=True)
                    
                    # 可选：打印工具调用情况
                    elif event["event"] == "on_tool_start":
                        tool_name = event.get("name", "")
                        tool_input = event.get("data", {}).get("input", {})
                        print(f"\n🔧 调用工具: {tool_name} 参数: {tool_input}")
                    
                    elif event["event"] == "on_tool_end":
                        tool_name = event.get("name", "")
                        output = event.get("data", {}).get("output", "")
                        if tool_name == "save_url":
                            print(f"\n✅ 已保存URL: {output}")
                    
            except Exception as e:
                print(f"\n\n❌ 执行过程中出现异常: {e}")
                print(f"此时已成功抓取到 {len(collected_urls)} 个URL")
            
            finally:
                print("\n\n====== 程序结束 ======")
                print("已收集的URL列表：")
                for idx, url in enumerate(collected_urls, 1):
                    print(f"{idx}. {url}")
                return collected_urls

if __name__ == "__main__":
    asyncio.run(run_agent_with_custom_tool())