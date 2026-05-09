# 正式版与测试版代码管理

本项目建议使用 Git worktree 同时维护两套运行代码：

- 正式版：`main` 分支，目录 `/home/zhongtie/zyl/doc`
- 测试版：`test` 分支，目录 `/home/zhongtie/zyl/doc-test`

这样测试版目录里的改动、热更新和运行端口不会影响正式版目录。

## 端口约定

| 环境 | 前端端口 | 后端端口 | 前端代理目标 |
| --- | ---: | ---: | --- |
| 正式版 | 62233 | 8009 | `http://127.0.0.1:8009` |
| 测试版 | 63230 | 8010 | `http://127.0.0.1:8010` |

正式版保持当前运行端口不变。测试版使用独立端口，避免和正式版进程冲突。

## 首次创建测试版工作区

在正式版目录执行：

```bash
cd /home/zhongtie/zyl/doc
git fetch origin
git worktree add ../doc-test -b test main
git push -u origin test
```

如果远端已经存在 `test` 分支，使用：

```bash
git worktree add ../doc-test test
```

## 启动正式版

正式版目录：

```bash
cd /home/zhongtie/zyl/doc
./scripts/start-official-backend.sh
./scripts/start-official-frontend.sh
```

访问：

```text
http://localhost:62233
```

## 启动测试版

测试版目录：

```bash
cd /home/zhongtie/zyl/doc-test
./scripts/start-test-backend.sh
./scripts/start-test-frontend.sh
```

访问：

```text
http://localhost:63230
```

## 日常开发流程

测试改动只在测试版目录做：

```bash
cd /home/zhongtie/zyl/doc-test
git status
git add .
git commit -m "Describe test change"
git push
```

测试通过后，再合并进正式版：

```bash
cd /home/zhongtie/zyl/doc
git pull
git merge --no-ff test
git push
```

合并后重启正式版服务，正式版才会使用测试通过的代码。

## 注意事项

- 不要直接在正式版目录改业务代码做试验。
- `.env`、上传文件、生成文件、`node_modules` 都不会提交到 Git。
- 两套目录可以同时运行，因为端口和运行时数据目录相互独立。
