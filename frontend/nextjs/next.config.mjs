/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  // Authenticated research data is always fetched from the same-origin API.
  // Do not register the former offline worker: its runtime cache could hide
  // source failures or reuse a previous session's responses.
  images: { unoptimized: true },
};
export default nextConfig;
