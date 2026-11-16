/** @type {import('tailwindcss').Config} */
// Tailwind v3 : n'utiliser que des classes v3 (pas de shadow-xs, outline-hidden, backdrop-blur-xs… propres à la v4).
module.exports = {
    content: ['./index.html', './assets/traduction.js'],
    theme: {
        extend: {
            // Apparition douce des modales (classe animate-fade-in)
            keyframes: {
                'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } }
            },
            animation: {
                'fade-in': 'fade-in 150ms ease-out'
            }
        }
    },
    plugins: []
};
