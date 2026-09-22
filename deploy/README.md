# PharmaScope 本机部署

当前机器的 80/443 已由 Nginx 统一入口，PharmaScope 使用独立 API 端口 `127.0.0.1:18180`，不会占用其他项目的端口。

## 一次性安装

在项目根目录执行下面一条命令。脚本会自动请求 root 权限、构建前端、切换 API 服务、申请证书并验证域名：

```bash
bash deploy/install.sh
```

脚本使用独立端口 `127.0.0.1:18180` 和独立 Nginx server block，不会占用其他项目的端口或域名。如果证书申请因 DNS 尚未生效失败，脚本会保留 HTTP 配置，DNS 生效后重新执行即可。

也可以显式使用 sudo：

```bash
sudo bash deploy/install.sh
```

部署完成后检查：

```bash
curl -fsS https://pharmascope.zimagent.top/healthz
```

## 更新前端

前端源码变更后，在项目根目录重新构建并复制静态产物：

```bash
NEXT_PUBLIC_PHARMA_API_URL='https://pharmascope.zimagent.top' \
NEXT_PUBLIC_PHARMA_WORKSPACE_ID='dee59b72-2cb2-5255-934c-b44a3fd8911c' \
npm --prefix frontend/nextjs run build
sudo rm -rf /var/www/pharmascope/current.new
sudo install -d /var/www/pharmascope/current.new
sudo cp -a frontend/nextjs/out/. /var/www/pharmascope/current.new/
sudo mv /var/www/pharmascope/current.new /var/www/pharmascope/current
```
