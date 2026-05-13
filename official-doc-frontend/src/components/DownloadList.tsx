import type { OutputFile } from '../types/document';

interface DownloadListProps {
  files: OutputFile[];
  getDownloadUrl: (file: OutputFile) => string;
}

export function DownloadList({ files, getDownloadUrl }: DownloadListProps) {
  if (files.length === 0) return null;

  return (
    <section className="success-box">
      <h2>生成结果</h2>
      <div className="download-list">
        {files.map((file) => (
          <a key={file.fileId || file.downloadUrl} href={getDownloadUrl(file)} target="_blank" rel="noreferrer">
            下载 {file.fileName || file.fileType || '文件'}
          </a>
        ))}
      </div>
    </section>
  );
}
