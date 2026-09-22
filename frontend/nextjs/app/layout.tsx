import type { Metadata } from "next";
import "./globals.css";
import "../components/pharma/pharma.css";

export const metadata: Metadata = {
  title: "PharmaScope Lite · 研发情报工作台",
  description: "可追溯的医药研发情报与临床试验变化追踪平台",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {

  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
