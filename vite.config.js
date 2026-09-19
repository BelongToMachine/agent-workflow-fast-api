import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { readdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { brotliCompress, constants as zlibConstants } from 'node:zlib'
import { promisify } from 'node:util'

const brotliCompressAsync = promisify(brotliCompress)
const brotliExtensions = new Set(['.css', '.html', '.js', '.json', '.svg', '.txt'])

async function collectBrotliFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = []

  for (const entry of entries) {
    const filePath = path.join(directory, entry.name)
    if (entry.isDirectory()) {
      files.push(...(await collectBrotliFiles(filePath)))
      continue
    }

    if (brotliExtensions.has(path.extname(entry.name))) {
      files.push(filePath)
    }
  }

  return files
}

function brotliStaticAssets() {
  return {
    name: 'brotli-static-assets',
    apply: 'build',
    async closeBundle() {
      const distDirectory = path.resolve(import.meta.dirname, 'dist')
      const files = await collectBrotliFiles(distDirectory)

      await Promise.all(
        files.map(async (filePath) => {
          const source = await readFile(filePath)
          const compressed = await brotliCompressAsync(source, {
            params: {
              [zlibConstants.BROTLI_PARAM_MODE]: zlibConstants.BROTLI_MODE_TEXT,
              [zlibConstants.BROTLI_PARAM_QUALITY]: 5,
            },
          })

          if (compressed.length < source.length) {
            await writeFile(`${filePath}.br`, compressed)
          }
        }),
      )
    },
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, import.meta.dirname, '')
  const fastApiTarget =
    env.VITE_FASTAPI_URL ||
    env.NEXT_PUBLIC_FASTAPI_BASE_URL ||
    env.FASTAPI_BASE_URL ||
    'http://127.0.0.1:8000'
  const workspaceId =
    env.VITE_WORKSPACE_ID ||
    env.NEXT_PUBLIC_WORKSPACE_ID ||
    '00000000-0000-0000-0000-000000000001'
  const singleWorkspaceMode =
    env.VITE_SINGLE_WORKSPACE_MODE ||
    env.NEXT_PUBLIC_SINGLE_WORKSPACE_MODE ||
    'true'

  return {
    define: {
      'process.env.NEXT_PUBLIC_API_MODE': JSON.stringify(env.NEXT_PUBLIC_API_MODE || 'fastapi-proxy'),
      'process.env.NEXT_PUBLIC_BASE_PATH': JSON.stringify(env.NEXT_PUBLIC_BASE_PATH ?? ''),
      'process.env.NEXT_PUBLIC_FASTAPI_BASE_URL': JSON.stringify(fastApiTarget),
      'process.env.NEXT_PUBLIC_WORKSPACE_ID': JSON.stringify(workspaceId),
      'process.env.NEXT_PUBLIC_SINGLE_WORKSPACE_MODE': JSON.stringify(singleWorkspaceMode),
      'process.env.NEXT_PUBLIC_USE_FASTAPI_BACKEND': JSON.stringify(env.NEXT_PUBLIC_USE_FASTAPI_BACKEND || '1'),
    },
    plugins: [react(), brotliStaticAssets()],
    server: {
      proxy: {
        '/api': {
          target: fastApiTarget,
          changeOrigin: true,
          secure: false,
          ws: true,
        },
      },
    },
    resolve: {
      alias: {
        '@': path.resolve(import.meta.dirname, 'src'),
      },
    },
    build: {
      chunkSizeWarningLimit: 3072,
    },
  }
})
