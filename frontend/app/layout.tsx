import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';

import '@genlayer/transaction-kit-react/styles.css';
import './globals.css';

import { Providers } from './providers';

export const metadata: Metadata = {
  title: 'Sentinel - Autonomous emergency halt for GenLayer',
  description:
    'An AI-judged emergency halt module: validators reach consensus on exploit evidence and protected contracts stop themselves, with no admin key and no vote.',
};

export const viewport: Viewport = {
  themeColor: '#04070d',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
