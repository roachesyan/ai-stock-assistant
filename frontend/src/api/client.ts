import axios from "axios";

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api",
  timeout: 60000,
});

// 响应拦截器：解析统一信封，success=false 时抛出可读错误。
client.interceptors.response.use(
  (resp) => {
    const body = resp.data;
    if (body && body.success === false) {
      const msg = body.error?.message ?? "请求失败";
      return Promise.reject(new Error(msg));
    }
    return resp;
  },
  (error) => {
    const body = error?.response?.data;
    const msg = body?.error?.message ?? error.message ?? "网络错误";
    return Promise.reject(new Error(msg));
  },
);

export default client;
