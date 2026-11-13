import type { Metadata } from 'next';
import './globals.css';
import '@xyflow/react/dist/style.css';
import { SessionProvider } from '@/lib/session';
import { ThemeProvider, THEME_BOOT_SCRIPT, DEFAULT_THEME } from '@/lib/theme';
import { Toaster } from '@/components/ui';

export const metadata: Metadata = {
  title: 'AIVANTA Relay',
  description: 'AIVANTA presales-to-delivery intelligence platform — n8n workflow automation edition',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme={DEFAULT_THEME} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,700;12..96,800&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono&display=swap"
        />
      </head>
      <body>
        <ThemeProvider>
          <SessionProvider>
            {children}
            <Toaster />
          </SessionProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
