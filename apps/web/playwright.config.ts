import {defineConfig} from '@playwright/test';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
export default defineConfig({
 testDir:'./e2e',workers:1,
 use:{baseURL:'http://localhost:5173',headless:true,launchOptions:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,args:['--no-sandbox']}:{}},
 reporter:[['list']],
 webServer:[
  {command:'npm run dev',url:'http://localhost:5173',reuseExistingServer:!process.env.CI,timeout:20000},
  {command:'python -m roundmind.serve',url:'http://127.0.0.1:8765/api/v1/health',reuseExistingServer:!process.env.CI,timeout:20000,
   env:{PYTHONPATH:resolve('../api'),ROUNDMIND_DATA_DIR:mkdtempSync(join(tmpdir(),'roundmind-e2e-'))}},
 ],
});
