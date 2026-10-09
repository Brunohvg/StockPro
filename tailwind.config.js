/**
 * Tailwind gerado no build (antes vinha do cdn.tailwindcss.com, que não é para produção).
 *
 * O CSS final (static/css/app.css) só contém as classes encontradas nos arquivos
 * de `content`. Ao criar telas, escreva as classes por extenso no template/JS/Python
 * ('text-rose-500'), nunca montadas por partes ('text-' + cor + '-500').
 *
 * Regerar: npm run build:css  (o Dockerfile também regera a cada deploy).
 */
module.exports = {
  content: [
    './templates/**/*.html',
    './apps/**/*.py',
    './static/js/**/*.js',
  ],
  theme: {
    extend: {
      // Igual ao tailwind.config que ficava inline no templates/base.html
      fontFamily: {
        sans: ['Plus Jakarta Sans', 'Inter', 'sans-serif'],
      },
      colors: {
        brand: {
          50: '#f0f4ff',
          100: '#e0e9fe',
          200: '#c1d3fe',
          300: '#92b2fd',
          400: '#5c89fa',
          500: '#345df1',
          600: '#2544e3',
          700: '#1d33cd',
          800: '#1e2ba6',
          900: '#1e2a84',
          950: '#11184f',
        },
      },
    },
  },
  plugins: [],
};
