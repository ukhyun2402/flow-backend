import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'e2e',timeout:90000,workers:1,use:{baseURL:process.env.FLOW_TEST_BASE_URL??'http://127.0.0.1:8080',channel:'msedge',headless:true,viewport:{width:1512,height:982},screenshot:'only-on-failure',trace:'retain-on-failure'},reporter:'list'});
