import type { Metadata } from "next";
import "./globals.css";
import "../components/pharma/pharma.css";

export const metadata: Metadata = {
  title: "PharmaScope Lite · 研发情报工作台",
  description: "可追溯的医药研发情报与临床试验变化追踪平台",
  icons: {
    icon: [{ url: "/brand/pharmascope-mark.svg", type: "image/svg+xml" }, { url: "/favicon.ico", sizes: "any" }],
    apple: "/brand/pharmascope-mark-180.png",
  },
  manifest: "/manifest.json",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {

  return (
    <html lang="zh-CN">
      <body>
        {children}
        <footer className="ps-site-footer">
          <a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">
            浙ICP备2026076087号-1
          </a>
        </footer>
      </body>
    </html>
  );
}
