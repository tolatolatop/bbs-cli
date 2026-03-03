# bbs-cli

基于 Click 的 Team BBS 命令行客户端，支持 `uv tool install` 安装后直接使用。

## 安装

```bash
uv tool install .
```

安装后可直接使用 `bbs` 命令：

```bash
bbs --help
bbs health check
```

## 认证与配置

- 默认配置文件：`~/.config/bbs-cli/config.json`
- `bbs auth login` 成功后会自动保存 token（可用 `--no-save` 关闭）

```bash
bbs auth register --username alice --password 123456 --nickname Alice
bbs auth login --username alice --password 123456
bbs auth me
bbs auth logout
```

## Base URL / Token 优先级

优先级从高到低：

1. CLI 参数：`--base-url`、`--token`
2. 环境变量：`BBS_BASE_URL`、`BBS_TOKEN`
3. 配置文件：`~/.config/bbs-cli/config.json`
4. 默认值：`http://127.0.0.1:60080`

```bash
BBS_BASE_URL=http://127.0.0.1:60080 bbs health check
BBS_TOKEN=your_token bbs auth me
```

## 命令分组

- `health`
- `auth`
- `users`
- `boards`
- `posts`
- `post`（`posts` 别名）
- `replies`
- `favorites`
- `favorite-boards`

## 常用示例

```bash
bbs users list -p 1 -s 10
bbs users get
bbs users get 1
bbs boards list
bbs boards create -n "General" -d "General discussion"

bbs posts list -p 1 -s 10 -b 1 -k hello
bbs posts create -b 1 -t "First post" -c "Hello world" --tags intro --tags welcome
bbs posts update 1 -t "Updated title"
bbs posts replies list 1
bbs posts replies create 1 -c "reply text"

bbs replies update 1 -c "new reply"
bbs replies delete 1

bbs favorites add -i 1
bbs favorites list
bbs favorites list -u 1
bbs favorite-boards add -b 1
bbs favorite-boards list
bbs favorite-boards list -u 1
```

## 短参数速查

- `-u` => `--user-id`（可选；不传默认使用当前登录用户）
- `-p` => `--page`
- `-i` => `--post-id`
- `-b` => `--board-id`
- `-t` => `--title`
- `-c` => `--content`
- `-s` => `--size`

## 大文本内容输入（post create）

`post` 与 `posts` 等价，以下示例都可换成 `bbs posts create`。

### 1) 直接传 `--content`

```bash
bbs post create -b 1 -t "Normal post" -c "Hello world"
```

### 2) 从 stdin 读取 content（适合长文本）

```bash
bbs post create -b 1 -t "Long post from stdin" <<'CONTENT'
This is a long article body.
Supports multiple lines from stdin.
CONTENT
```

### 3) `--json` 传 JSON 字符串

```bash
bbs post create -j '{"board_id":1,"title":"json title","content":"json content","tags":["a","b"]}'
```

### 4) `--json @file.json` 从文件读取 JSON

```bash
bbs post create -j @post.json
```

### 5) `--json @-` 从 stdin 读取 JSON

```bash
bbs post create -j @- <<'JSON'
{"board_id":1,"title":"stdin json","content":"content from stdin json"}
JSON
```

## 故障排查

- 命令不存在：执行 `uv tool list` 检查是否安装成功。
- 返回 401：先执行 `bbs auth login`，或设置 `BBS_TOKEN`。
- 变更后命令未更新：执行 `uv tool install --force --reinstall --refresh .`。

## 输出约定

- JSON 默认使用 UTF-8 直接输出（中文不转义）。
- 时间字段（如 `created_at`、`updated_at`）统一转换为上海时区（`Asia/Shanghai`），格式为 `YYYY-MM-DD HH:MM:SS`（精确到秒）。
