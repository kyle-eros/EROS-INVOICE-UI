/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async redirects() {
    return [
      { source: '/invoicing', destination: '/admin', permanent: true },
      { source: '/admin/reminders', destination: '/admin', permanent: true },
    ];
  },
};

export default nextConfig;
