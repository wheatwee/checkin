# checkin

## v2free配置参数

依次点击上栏【Setting】->【Security】->【Secrets】->【Actions】->【New repository secrets】 添加账号和密码等信息，示例如下：

| key    | value                      |
| ------ | -------------------------- |
| USER   | 123@qq.com,567@outlook.com |
| PWD    | ccc,aaa                    |
| remail | abc@163.com                |
| semail | cdc@163.com                |
| secode | sakdjdiunerhv              |

## workbuddy配置参数

仓库 → Settings → Secrets and variables → Actions → New repository secret：

| Name               | Value                                        | 必填 |
| ------------------ | -------------------------------------------- | ---- |
| WORKBUDDY_ACCOUNTS | 整个 签到token.json（或 accounts.json）的内容 | 必填 |
| PUSHPLUS_TOKEN     | PushPlus token（微信推送，见下）             | 可选 |
| SERVERCHAN_KEY     | Server酱 SendKey（微信推送备选）             | 可选 |

注意：accounts.json 里带 _status/_detail 字段，脚本只用到 name+token，不影响。

格式：
```json
{"accounts":[{"name":"鸵鸟","token":"<从 workbuddy-desktop.info 读取的 accessToken>"}]}
```
