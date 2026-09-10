"""开发启动入口:python scripts/serve.py

启动命令里传的是字符串 "researchpilot.app.api:app" 而不是 app 对象,
格式是 "模块路径:对象名"。原因:uvicorn 需要按字符串重新导入应用,
这样它才能控制(并热重载)模块生命周期。直接传对象在 reload 时会失效。

dev 想改代码自动重启:把 uvicorn 装成带 extras 的版本
(pip install "uvicorn[standard]")后,把下面 run 的 reload 参数设为 True。
"""
import os

import uvicorn

if __name__ == "__main__":
    # 默认 8001:与花生壳内网穿透映射的端口保持一致,启动即对外可用。
    # RP_PORT 仍可覆盖(如换端口演示)。
    uvicorn.run(
        "researchpilot.app.api:app",
        host="127.0.0.1",
        port=int(os.getenv("RP_PORT", "8001")),
    )
