import js from '@eslint/js'
import vue from 'eslint-plugin-vue'
import tseslint from 'typescript-eslint'
export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**', 'test-results/**', 'test-artifacts/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...vue.configs['flat/essential'],
  { files: ['**/*.vue'], languageOptions: { parserOptions: { parser: tseslint.parser, extraFileExtensions: ['.vue'] } }, rules: { 'vue/multi-word-component-names': 'off' } },
  { rules: { '@typescript-eslint/no-explicit-any': 'off', '@typescript-eslint/no-unused-vars': 'off', '@typescript-eslint/no-unused-expressions': 'off', 'no-useless-escape': 'off', 'no-useless-assignment': 'off', 'no-undef': 'off' } },
)
