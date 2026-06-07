import { useCallback, useEffect, useState } from "react";
import {
  ModelEntry,
  ModelUpdate,
  activateModel,
  checkModelUpdates,
  downloadModelUpdate,
  fetchModelRegistry,
  importLocalModel,
  uninstallModel,
} from "../lib/api";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Progress } from "./ui/progress";

export function ModelSettings() {
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [updates, setUpdates] = useState<ModelUpdate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [downloadingModel, setDownloadingModel] = useState<string | null>(null);
  const [downloadProgress, setDownloadProgress] = useState(0);

  const loadModels = useCallback(async () => {
    try {
      setLoading(true);
      const registry = await fetchModelRegistry();
      setModels(registry.models);
      setActiveId(registry.active_id);
      setError("");
    } catch (err: unknown) {
      const withDetail = err as { response?: { data?: { detail?: string } }; message?: string };
      setError(withDetail.response?.data?.detail || withDetail.message || "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadModels();
  }, [loadModels]);

  const handleCheckUpdates = async () => {
    try {
      setActionMessage("检查更新中...");
      const result = await checkModelUpdates();
      setUpdates(result.updates);
      if (result.updates.length === 0) {
        setActionMessage("已是最新版本");
      } else {
        setActionMessage(`发现 ${result.updates.length} 个可用更新`);
      }
    } catch (err: unknown) {
      const withDetail = err as { response?: { data?: { detail?: string } }; message?: string };
      setActionMessage(withDetail.response?.data?.detail || "检查更新失败");
    }
  };

  const handleActivate = async (modelId: string) => {
    try {
      setActionMessage("切换中...");
      await activateModel(modelId);
      setActiveId(modelId);
      setActionMessage("切换成功");
      await loadModels();
    } catch (err: unknown) {
      const withDetail = err as { response?: { data?: { detail?: string } }; message?: string };
      setActionMessage(withDetail.response?.data?.detail || "切换失败");
    }
  };

  const handleDownload = async (modelId: string, url?: string, version?: string) => {
    try {
      setDownloadingModel(modelId);
      setDownloadProgress(0);
      setActionMessage("下载中...");

      // Simulate progress (real progress would require WebSocket)
      const progressInterval = setInterval(() => {
        setDownloadProgress((prev) => Math.min(prev + 5, 90));
      }, 500);

      await downloadModelUpdate(modelId, url || "", version || "");

      clearInterval(progressInterval);
      setDownloadProgress(100);
      setActionMessage("下载完成");
      await loadModels();
    } catch (err: unknown) {
      const withDetail = err as { response?: { data?: { detail?: string } }; message?: string };
      setActionMessage(withDetail.response?.data?.detail || "下载失败");
    } finally {
      setDownloadingModel(null);
      setDownloadProgress(0);
    }
  };

  const handleImport = async () => {
    try {
      const input = document.createElement("input");
      input.type = "file";
      input.setAttribute("webkitdirectory", "");
      input.onchange = async () => {
        const files = input.files;
        if (!files || files.length === 0) return;

        // Get directory path from first file
        const firstFile = files[0];
        const pathParts = firstFile.webkitRelativePath.split("/");
        const dirName = pathParts[0];

        setActionMessage("导入中...");
        await importLocalModel(dirName, "sensevoice-int8");
        setActionMessage("导入成功");
        await loadModels();
      };
      input.click();
    } catch (err: unknown) {
      const withDetail = err as { response?: { data?: { detail?: string } }; message?: string };
      setActionMessage(withDetail.response?.data?.detail || "导入失败");
    }
  };

  const handleUninstall = async (modelId: string) => {
    if (!confirm("确定要卸载此模型吗？")) return;
    try {
      setActionMessage("卸载中...");
      await uninstallModel(modelId);
      setActionMessage("卸载成功");
      await loadModels();
    } catch (err: unknown) {
      const withDetail = err as { response?: { data?: { detail?: string } }; message?: string };
      setActionMessage(withDetail.response?.data?.detail || "卸载失败");
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes > 1024 * 1024 * 1024) {
      return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
    }
    if (bytes > 1024 * 1024) {
      return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    }
    return `${(bytes / 1024).toFixed(1)} KB`;
  };

  if (loading) {
    return (
      <Card className="p-6">
        <div className="text-center text-muted-foreground">加载中...</div>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">模型管理</h2>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={handleCheckUpdates}>
              检查更新
            </Button>
            <Button variant="outline" size="sm" onClick={handleImport}>
              导入本地模型
            </Button>
          </div>
        </div>

        {actionMessage && (
          <div className="mb-4 p-3 bg-muted/50 rounded-lg text-sm">
            {actionMessage}
          </div>
        )}

        {error && (
          <div className="mb-4 p-3 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-900 rounded-lg text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        )}

        <div className="space-y-4">
          {models.length === 0 ? (
            <div className="text-center text-muted-foreground py-8">
              暂无已安装的模型
            </div>
          ) : (
            models.map((model) => (
              <div
                key={model.id}
                className={`p-4 rounded-lg border ${
                  model.active
                    ? "border-primary bg-primary/5"
                    : "border-border"
                }`}
              >
                <div className="flex items-start justify-between">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{model.name}</span>
                      {model.active && (
                        <span className="text-xs bg-primary text-primary-foreground px-2 py-0.5 rounded">
                          当前使用
                        </span>
                      )}
                    </div>
                    <div className="text-sm text-muted-foreground">
                      版本: {model.version} | 引擎: {model.engine}
                    </div>
                    <div className="text-sm text-muted-foreground">
                      路径: {model.path}
                    </div>
                    {model.files.length > 0 && (
                      <div className="text-xs text-muted-foreground">
                        文件: {model.files.map((f) => f.filename).join(", ")}
                      </div>
                    )}
                  </div>
                  <div className="flex gap-2">
                    {!model.active && model.installed && (
                      <Button
                        size="sm"
                        onClick={() => handleActivate(model.id)}
                      >
                        激活
                      </Button>
                    )}
                    {model.id !== "sensevoice-int8" && (
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => handleUninstall(model.id)}
                      >
                        卸载
                      </Button>
                    )}
                  </div>
                </div>

                {downloadingModel === model.id && (
                  <div className="mt-3">
                    <Progress value={downloadProgress} className="h-2" />
                    <div className="text-xs text-muted-foreground mt-1">
                      下载中... {downloadProgress}%
                    </div>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </Card>

      {updates.length > 0 && (
        <Card className="p-6">
          <h3 className="text-lg font-semibold mb-4">可用更新</h3>
          <div className="space-y-3">
            {updates.map((update) => (
              <div
                key={update.id}
                className="flex items-center justify-between p-3 bg-muted/50 rounded-lg"
              >
                <div>
                  <div className="font-medium">{update.name}</div>
                  <div className="text-sm text-muted-foreground">
                    {update.current_version
                      ? `${update.current_version} → ${update.remote_version}`
                      : `新模型: ${update.remote_version}`}
                  </div>
                </div>
                <Button
                  size="sm"
                  onClick={() => handleDownload(update.id)}
                  disabled={downloadingModel === update.id}
                >
                  {downloadingModel === update.id ? "下载中..." : "更新"}
                </Button>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card className="p-6">
        <h3 className="text-lg font-semibold mb-4">模型说明</h3>
        <div className="space-y-2 text-sm text-muted-foreground">
          <p>
            <strong>SenseVoice INT8:</strong> 语音识别模型，支持中文、英文、日文、韩文、粤语。
          </p>
          <p>
            <strong>Silero VAD:</strong> 语音活动检测模型，用于智能分段。
          </p>
          <p>
            模型存储位置: <code className="bg-muted px-1 rounded">~/.local/share/echosmith/models/</code>
          </p>
        </div>
      </Card>
    </div>
  );
}
