import os
from zhipuai import ZhipuAI

api_key = os.getenv("ZHIPU_API_KEY")
if not api_key:
    raise SystemExit("请先设置环境变量 ZHIPU_API_KEY")

client = ZhipuAI(api_key=api_key)

def chat(prompt: str, model: str = "glm-4.7-flash") -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=512,
    )
    return resp.choices[0].message.content

if __name__ == "__main__":
    print("模型回复：")
    print(chat("用三句话解释什么是 MoE 模型。"))
