import os, dotenv
from browser_use import Agent
# 关键修改：使用 browser_use 内置的 ChatOpenAI
from browser_use.llm import ChatOpenAI
import asyncio

dotenv.load_dotenv()

# 在创建 llm 之前，强制设置环境变量
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")


async def main():
    # 1. 替换为你的阿里云百炼 API Key
    llm = ChatOpenAI(
        model="qwen-plus",  # 可以选择 qwen-max, qwen-turbo, qwen-long 等其他模型
        temperature=0.7,
        # openai_api_base="https://dashscope.aliyuncs.com/compatible-mode/v1", # 国内地域使用
        # openai_api_base="https://dashscope-intl.aliyuncs.com/compatible-mode/v1", # 若需使用新加坡等海外地域，改用此地址
    )

    agent = Agent(
        task = """
访问网页 https://campus.game.163.com/position，完成以下任务：

1. 定位左侧筛选区域的“职位类型”分类，找到并点击“游戏研发与技术类”选项。等待页面刷新，只显示技术类职位。

2. 确认页面上的职位列表已更新后，依次提取每个技术类职位的详情页 URL：
   - 模拟点击当前职位名称（不要点击筛选器或其他链接）
   - 新标签页打开后，切换到该标签页，复制完整地址栏中的 URL
   - 关闭详情页标签页，返回到职位列表页
   - 继续处理下一个职位，直到列表中所有技术类岗位都被处理完毕

3. 返回所有收集到的技术类职位详情页 URL 列表，每行一个。
""",
        llm=llm,
    )

    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())