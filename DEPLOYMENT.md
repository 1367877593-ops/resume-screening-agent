# 发布为可分享的 Web Demo

推荐使用 Streamlit Community Cloud。部署后，使用者只需打开一个
`https://*.streamlit.app` 链接，不需要安装 Python。

## 1. 创建应用

打开 <https://share.streamlit.io>，使用 GitHub 登录并创建应用：

- Repository：`1367877593-ops/resume-screening-agent`
- Branch：`main`
- Main file path：`app/main.py`
- Python：`3.12`

## 2. 安全配置 Secrets

进入 **Advanced settings → Secrets**。参考
`.streamlit/secrets.toml.example`，在云端界面填写真实值。

必须设置：

- `LLM_API_KEY`：DeepSeek 临时低额度 Key
- `APP_ACCESS_CODE`：与 API Key 不同的随机强口令，至少 12 位
- `LLM_MODEL = "deepseek-v4-pro"`
- `DEMO_MODE = false`

不要创建或上传真实的 `.streamlit/secrets.toml`，也不要把 Secret 粘贴到
GitHub、Issue、聊天或截图中。Community Cloud 会把根级 Secret 安全地作为
环境变量提供给应用。

## 3. 分享与费用保护

仓库是公开的，因此应用默认也是公开的；本项目会先显示访问口令页，只有口令
正确才会加载上传与分析界面。仅将应用 URL 和访问口令发给需要试用的人。

默认限制：

- 单次最多 5 份简历
- 单文件上传上限 10 MB
- 单次简历总大小 20 MB
- JD 最多 20,000 字符
- 相同输入命中缓存，避免重复调用

仍建议在 DeepSeek 控制台设置低余额/低预算，试用结束后撤销云端 Key。

## 4. 验收

部署成功后，确认：

1. 未输入访问口令时看不到上传界面；
2. 输入正确口令后，侧边栏显示 `deepseek / deepseek-v4-pro`；
3. 侧边栏只显示“API Key 已安全加载”，不会显示 Key；
4. 上传一份非敏感测试简历可完成真实分析。
