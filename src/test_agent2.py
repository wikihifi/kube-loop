import os
import openlit
from openhands.sdk import LLM, Agent, Conversation
from openhands.sdk.tool import Tool, register_tool
from openhands.tools.terminal import TerminalTool
from openhands.tools.file_editor import FileEditorTool

# Register external tools by string name
register_tool("TerminalTool", TerminalTool)
register_tool("FileEditorTool", FileEditorTool)

# Initialize OpenLIT telemetry
openlit.init(otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))

llm = LLM(
    model=os.getenv("LLM_MODEL"),
    api_key=os.getenv("LLM_API_KEY"),
)

agent = Agent(
    llm=llm,
    tools=[
        Tool(name="TerminalTool"),
        Tool(name="FileEditorTool"),
    ],
)

conversation = Conversation(agent=agent, workspace=os.getcwd())
conversation.send_message(
    "List the files in the current directory and write a one-line summary to SUMMARY.txt"
)
conversation.run()
print("Done — check http://localhost:3000 for traces")