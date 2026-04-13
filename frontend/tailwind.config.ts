import type { Config } from 'tailwindcss';
import animate from 'tailwindcss-animate';

const colorToken = (token: string) => `hsl(var(${token}) / <alpha-value>)`;

const config = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    container: {
      center: true,
      padding: '1.5rem',
      screens: {
        '2xl': '1440px',
      },
    },
    extend: {
      colors: {
        border: colorToken('--border'),
        input: colorToken('--input'),
        ring: colorToken('--ring'),
        background: colorToken('--background'),
        foreground: colorToken('--foreground'),
        primary: {
          DEFAULT: colorToken('--primary'),
          foreground: colorToken('--primary-foreground'),
        },
        secondary: {
          DEFAULT: colorToken('--secondary'),
          foreground: colorToken('--secondary-foreground'),
        },
        destructive: {
          DEFAULT: colorToken('--destructive'),
          foreground: colorToken('--destructive-foreground'),
        },
        muted: {
          DEFAULT: colorToken('--muted'),
          foreground: colorToken('--muted-foreground'),
        },
        accent: {
          DEFAULT: colorToken('--accent'),
          foreground: colorToken('--accent-foreground'),
        },
        popover: {
          DEFAULT: colorToken('--popover'),
          foreground: colorToken('--popover-foreground'),
        },
        card: {
          DEFAULT: colorToken('--card'),
          foreground: colorToken('--card-foreground'),
        },
        panel: {
          DEFAULT: colorToken('--panel'),
          foreground: colorToken('--panel-foreground'),
          muted: colorToken('--panel-muted'),
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      boxShadow: {
        shell: '0 24px 80px rgba(2, 6, 23, 0.42)',
        panel: '0 18px 48px rgba(15, 23, 42, 0.28)',
      },
      keyframes: {
        'accordion-down': {
          from: { height: '0' },
          to: { height: 'var(--radix-accordion-content-height)' },
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: '0' },
        },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
      },
    },
  },
  plugins: [animate],
} satisfies Config;

export default config;