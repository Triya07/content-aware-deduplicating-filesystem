import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000/api";
const pages = [
  ["dashboard", "Dashboard", "⌂"],
  ["files", "File Manager", "▣"],
  ["chunks", "Chunk Explorer", "◈"],
  ["analytics", "Deduplication Analytics", "◒"],
  ["references", "Reference Monitor", "↔"],
  ["lab", "Deduplication Lab", "✦"],
  ["stress", "Stress Testing", "⚡"],
  ["activity", "Activity Logs", "◷"],
];

const formatBytes = (value = 0) => {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let number = value;
  let unit = -1;
  do { number /= 1024; unit += 1; } while (number >= 1024 && unit < units.length - 1);
  return `${number.toFixed(number >= 10 ? 0 : 1)} ${units[unit]}`;
};

function request(path, options) {
  return fetch(`${API}${path}`, options).then(async (response) => {
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || "The API request failed");
    return body;
  });
}

function App() {
  const [page, setPage] = useState("dashboard");
  const [dashboard, setDashboard] = useState(null);
  const [files, setFiles] = useState([]);
  const [chunks, setChunks] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [references, setReferences] = useState([]);
  const [activities, setActivities] = useState([]);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setError("");
      const [nextDashboard, nextFiles, nextChunks, nextAnalytics, nextReferences, nextActivities] =
        await Promise.all([
          request("/dashboard"), request("/files"), request("/chunks"),
          request("/analytics"), request("/reference-counts"), request("/activities"),
        ]);
      setDashboard(nextDashboard);
      setFiles(nextFiles);
      setChunks(nextChunks);
      setAnalytics(nextAnalytics);
      setReferences(nextReferences);
      setActivities(nextActivities);
    } catch (reason) {
      setError(reason.message);
    }
  }, []);

  useEffect(() => { refresh(); const timer = setInterval(refresh, 5000); return () => clearInterval(timer); }, [refresh]);

  const view = {
    dashboard: <Dashboard data={dashboard} files={files} chunks={chunks} onNavigate={setPage} />,
    files: <FileManager files={files} refresh={refresh} />,
    chunks: <ChunkExplorer chunks={chunks} />,
    analytics: <Analytics data={analytics} />,
    references: <ReferenceMonitor references={references} />,
    lab: <DeduplicationLab files={files} refresh={refresh} />,
    stress: <StressTesting files={files} refresh={refresh} />,
    activity: <ActivityLogs activities={activities} />,
  }[page];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-mark">CA</div>
        <div className="brand">
          <strong>CONTENT-AWARE</strong>
          <span>DEDUPLICATING FILESYSTEM</span>
        </div>
        <div className="sidebar-label">WORKSPACE</div>
        <nav>{pages.map(([key, label, icon]) =>
          <button key={key} className={page === key ? "nav-item active" : "nav-item"} onClick={() => setPage(key)}>
            <span>{icon}</span>{label}
          </button>)}</nav>
        <div className="sidebar-footer">
          <span className={dashboard?.filesystem_mounted ? "status-dot online" : "status-dot"} />
          <div><b>{dashboard?.filesystem_mounted ? "Filesystem mounted" : "Filesystem offline"}</b><small>{dashboard?.mountpoint_configured || "mountpoint"}</small></div>
        </div>
      </aside>
      <main className="main-content">
        <header className="topbar"><div><p className="eyebrow">INTELLIGENT STORAGE MANAGEMENT SYSTEM</p><h1>{pages.find(([key]) => key === page)?.[1]}</h1></div><button className="refresh" onClick={refresh}>↻ Refresh</button></header>
        {error && <div className="error-banner">Unable to reach the API: {error}</div>}
        {view}
      </main>
    </div>
  );
}

function Dashboard({ data, files, chunks, onNavigate }) {
  if (!data) return <Loading />;
  const cards = [
    ["Total files", data.total_files, "↗", ""],
    ["Unique chunks", data.total_unique_chunks, "◈", ""],
    ["Logical storage", formatBytes(data.logical_storage), "▤", ""],
    ["Physical storage", formatBytes(data.physical_storage), "◉", ""],
    ["Storage saved", formatBytes(data.storage_saved), "✦", "positive"],
    ["Deduplication", `${data.deduplication_percentage}%`, "◒", "positive"],
  ];
  return <section>
    <div className="hero"><div><span className="pill">LIVE STORAGE TELEMETRY</span><h2>Make every byte count.</h2><p>Monitor content-addressed storage, and savings in real time. Active chunk size: {formatBytes(data.chunk_size)}.</p></div><button className="primary" onClick={() => onNavigate("files")}>Upload files <span>→</span></button></div>
    <div className="stats-grid">{cards.map(([label, value, icon, tone]) => <div className={`stat-card ${tone}`} key={label}><div className="stat-icon">{icon}</div><span>{label}</span><strong>{value}</strong></div>)}</div>
    <div className="dashboard-grid">
      <Panel title="Storage efficiency" action={`${data.duplicate_chunks} shared chunks`}><StorageBars data={data} /></Panel>
      <Panel title="System snapshot"><div className="snapshot"><Metric label="Duplicate references" value={data.duplicate_references} /><Metric label="References / chunk" value={data.average_references_per_chunk} /><Metric label="Total references" value={data.total_references} /></div><div className="mini-link" onClick={() => onNavigate("references")}>Explore relationships <span>→</span></div></Panel>
    </div>
    <Panel title="Recent files" action="View all" onAction={() => onNavigate("files")}><div className="compact-list">{files.slice(0, 5).map(file => <div className="compact-row" key={file.path}><span className="file-chip">FILE</span><b>{file.filename}</b><small>{file.chunk_count} chunks · {formatBytes(file.size)}</small></div>)}{!files.length && <Empty text="Upload your first file to begin exploring deduplication." />}</div></Panel>
    <div className="insight"><span className="insight-icon">✦</span><div><b>Deduplication insight</b><p>{data.storage_saved ? `Your content-addressed store is currently saving ${formatBytes(data.storage_saved)} by reusing identical chunks.` : "Upload identical or related files to see storage savings appear here."}</p></div></div>
  </section>;
}

function FileManager({ files, refresh }) {
  const [selected, setSelected] = useState([]);
  const [uploads, setUploads] = useState([]);
  const inputRef = useRef(null);
  const uploadOne = (file) => new Promise((resolve) => {
    const form = new FormData(); form.append("files", file);
    const xhr = new XMLHttpRequest(); xhr.open("POST", `${API}/files/upload`);
    xhr.upload.onprogress = (event) => event.lengthComputable && setUploads(old => old.map(item => item.name === file.name ? { ...item, progress: Math.round(event.loaded / event.total * 100) } : item));
    xhr.onload = () => { const result = xhr.status >= 200 && xhr.status < 300 ? "uploaded" : "failed"; setUploads(old => old.map(item => item.name === file.name ? { ...item, progress: 100, status: result } : item)); resolve(); };
    xhr.onerror = () => { setUploads(old => old.map(item => item.name === file.name ? { ...item, status: "failed" } : item)); resolve(); };
    xhr.send(form);
  });
  const upload = async (list) => {
    const filesToUpload = [...list];
    setUploads(filesToUpload.map(file => ({ name: file.name, size: file.size, progress: 0, status: "uploading" })));
    for (const file of filesToUpload) await uploadOne(file);
    await refresh();
  };
  const remove = async (name) => { if (!window.confirm(`Delete ${name}?`)) return; await request(`/files/${encodeURIComponent(name)}`, { method: "DELETE" }); setSelected(old => old.filter(item => item !== name)); refresh(); };
  const batchDelete = async () => { for (const name of selected) await request(`/files/${encodeURIComponent(name)}`, { method: "DELETE" }); setSelected([]); refresh(); };
  return <section>
    <div className="section-heading"><div><h2>File workspace</h2><p>Manage virtual files through the mounted storage engine.</p></div><button className="primary" onClick={() => inputRef.current?.click()}>＋ Add files</button><input ref={inputRef} hidden type="file" multiple onChange={event => upload(event.target.files)} /></div>
    <Dropzone onFiles={upload} />
    {uploads.length > 0 && <div className="upload-queue panel"><div className="panel-title"><h3>Upload queue</h3><span>{uploads.filter(item => item.status === "uploaded").length}/{uploads.length} complete</span></div>{uploads.map(item => <div className="upload-item" key={item.name}><span className="file-chip">FILE</span><b>{item.name}</b><div className="progress"><i style={{ width: `${item.progress}%` }} /></div><small>{item.status === "failed" ? "Failed" : item.status === "uploaded" ? "Complete" : `${item.progress}%`}</small></div>)}</div>}
    <Panel title={`${files.length} files`} action={selected.length ? `Delete ${selected.length} selected` : ""} onAction={batchDelete}><div className="table-wrap"><table><thead><tr><th><input type="checkbox" checked={selected.length === files.length && files.length > 0} onChange={event => setSelected(event.target.checked ? files.map(file => file.filename) : [])} /></th><th>Filename</th><th>Size</th><th>Chunks</th><th>Actions</th></tr></thead><tbody>{files.map(file => <tr key={file.path}><td><input type="checkbox" checked={selected.includes(file.filename)} onChange={event => setSelected(old => event.target.checked ? [...old, file.filename] : old.filter(name => name !== file.filename))} /></td><td><b>{file.filename}</b></td><td>{formatBytes(file.size)}</td><td><span className="tag">{file.chunk_count} chunks</span></td><td className="actions"><a href={`${API}/files/${encodeURIComponent(file.filename)}/download`} download>Download</a><button onClick={() => remove(file.filename)}>Delete</button></td></tr>)}</tbody></table>{!files.length && <Empty text="No files stored yet." />}</div></Panel>
  </section>;
}

function Dropzone({ onFiles }) {
  const [dragging, setDragging] = useState(false);
  return <div className={`dropzone ${dragging ? "dragging" : ""}`} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); onFiles(event.dataTransfer.files); }}><span className="upload-icon">↑</span><div><b>Drop files here to upload</b><small>Multiple files and all file types supported</small></div></div>;
}

function ChunkExplorer({ chunks }) {
  return <section><div className="section-heading"><div><h2>Unique chunk inventory</h2><p>Every chunk is content-addressed by its SHA-256 digest.</p></div><span className="pill">{chunks.length} unique chunks</span></div><Panel title="Chunk explorer"><div className="table-wrap"><table><thead><tr><th>Digest</th><th>Size</th><th>References</th><th>Files sharing it</th><th>Storage location</th></tr></thead><tbody>{chunks.map(chunk => <tr key={chunk.digest}><td><code>{chunk.digest.slice(0, 18)}…</code></td><td>{formatBytes(chunk.size)}</td><td><span className={chunk.reused ? "reference-badge shared" : "reference-badge"}>{chunk.reference_count} {chunk.reused ? "shared" : "reference"}</span></td><td>{chunk.files?.join(", ") || "—"}</td><td className="muted">{chunk.storage_location}</td></tr>)}</tbody></table>{!chunks.length && <Empty text="Chunks will appear after files are uploaded." />}</div></Panel></section>;
}

function Analytics({ data }) {
  if (!data) return <Loading />;
  return <section><div className="section-heading"><div><h2>Storage analytics</h2><p>Actual logical versus physical storage from SQLite metadata.</p></div><span className="pill positive-pill">{data.deduplication_percentage}% saved</span></div><div className="analytics-layout"><Panel title="Storage comparison"><StorageBars data={data} large /></Panel><div className="stats-stack"><MetricCard label="Logical storage" value={formatBytes(data.logical_storage)} /><MetricCard label="Physical storage" value={formatBytes(data.physical_storage)} /><MetricCard label="Storage saved" value={formatBytes(data.storage_saved)} tone="positive" /><MetricCard label="Average references / chunk" value={data.average_references_per_chunk} /></div></div><Panel title="Deduplication formula"><div className="formula"><span>({formatBytes(data.logical_storage)} logical − {formatBytes(data.physical_storage)} physical)</span><b>= {formatBytes(data.storage_saved)} saved</b><strong>{data.deduplication_percentage}% deduplication</strong></div></Panel></section>;
}

function ReferenceMonitor({ references }) {
  return <section><div className="section-heading"><div><h2>Reference relationships</h2><p>Live file-to-chunk mappings and safe reference counts.</p></div></div><div className="relationship-grid">{references.map(item => <div className="relationship-card" key={item.digest}><div className="relationship-head"><code>{item.digest.slice(0, 16)}…</code><span className="reference-badge shared">{item.reference_count} refs</span></div><div className="relationship-line" />{item.files.map(file => <div className="file-node" key={file}><span>FILE</span>{file}</div>)}<small>{formatBytes(item.size)} chunk · {item.reference_count > 1 ? "shared across files" : "single-file chunk"}</small></div>)}{!references.length && <Empty text="No relationships yet." />}</div></section>;
}

function DeduplicationLab({ files, refresh }) {
  const [selected, setSelected] = useState([]);
  const [result, setResult] = useState(null);
  const run = async () => { setResult({ status: "running" }); try { setResult({ status: "complete", ...(await request("/lab/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filenames: selected }) })) }); } catch (error) { setResult({ status: "failed", error: error.message }); } await refresh(); };
  return <section><div className="section-heading"><div><h2>Deduplication Lab</h2><p>Select any number of real files and inspect the result from file_chunks and chunks.</p></div><button className="primary" disabled={!selected.length} onClick={run}>Run analysis</button></div><Panel title={`Select files · ${selected.length} selected`}><div className="lab-files">{files.map(file => <label key={file.path} className={selected.includes(file.filename) ? "lab-file selected" : "lab-file"}><input type="checkbox" checked={selected.includes(file.filename)} onChange={event => setSelected(old => event.target.checked ? [...old, file.filename] : old.filter(name => name !== file.filename))} /><span className="file-chip">FILE</span><b>{file.filename}</b><small>{formatBytes(file.size)} · {file.chunk_count} chunks</small></label>)}</div>{!files.length && <Empty text="Upload files before running an analysis." />}</Panel>{result?.status === "failed" && <div className="error-banner">{result.error}</div>}{result?.status === "complete" && <div className="result-grid"><MetricCard label="Files processed" value={result.total_files_processed} /><MetricCard label="Chunk references" value={result.total_chunks_generated} /><MetricCard label="Unique chunks" value={result.new_unique_chunks_stored} /><MetricCard label="Shared chunks reused" value={result.existing_chunks_reused} /><MetricCard label="Duplicate occurrences" value={result.duplicate_chunks_detected} /><MetricCard label="Total references" value={result.total_reference_count} /><MetricCard label="Storage saved" value={formatBytes(result.storage_saved)} tone="positive" /><MetricCard label="Physical storage" value={formatBytes(result.physical_storage)} /></div>}</section>;
}

function StressTesting({ files, refresh }) {
  const [scenario, setScenario] = useState("identical");
  const [status, setStatus] = useState(null);
  const scenarios = { identical: "All files identical", different: "All files different", partial: "Partially identical content", shared: "Common chunk sharing", deletion: "Shared chunk deletion safety", modify: "Shared chunk modification safety" };
  const run = async () => { setStatus({ running: true }); try { setStatus(await request("/stress-tests", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario, count: 5 }) })); } catch (error) { setStatus({ error: error.message }); } await refresh(); };
  return <section><div className="section-heading"><div><h2>Stress testing</h2><p>Run repeatable demonstrations against the real filesystem.</p></div><span className="pill">{files.length} current files</span></div><div className="scenario-grid">{Object.entries(scenarios).map(([key, label]) => <button key={key} className={scenario === key ? "scenario selected" : "scenario"} onClick={() => setScenario(key)}><b>{label}</b><small>{key === "deletion" || key === "modify" ? "Safety validation" : "Deduplication workload"}</small></button>)}</div><Panel title="Scenario runner"><p className="muted">{status?.running ? "Processing aligned 4096-byte blocks through DedupStore…" : status?.error || (status ? `${status.passed ? "PASS" : "FAIL"} · ${status.files_processed} files · ${status.scenario_after.shared_chunks} shared chunks · ${formatBytes(status.scenario_after.storage_saved)} saved.` : "Choose a scenario and run it against the real storage engine.")}</p>{status && !status.running && !status.error && <div className="result-grid"><MetricCard label="Chunk references" value={status.scenario_after.chunk_references} /><MetricCard label="Unique chunks" value={status.scenario_after.unique_chunks} /><MetricCard label="Shared chunks" value={status.scenario_after.shared_chunks} /><MetricCard label="Duplicate occurrences" value={status.scenario_after.duplicate_occurrences} /><MetricCard label="Physical storage" value={formatBytes(status.scenario_after.physical_storage)} /><MetricCard label="Storage saved" value={formatBytes(status.scenario_after.storage_saved)} tone="positive" /></div>}<button className="primary" onClick={run} disabled={status?.running}>Run scenario</button></Panel></section>;
}

function ActivityLogs({ activities }) {
  return <section><div className="section-heading"><div><h2>Activity logs</h2><p>Events emitted by the storage engine, not fabricated by the UI.</p></div></div><Panel title="Storage event stream"><div className="activity-list">{activities.map(activity => <div className="activity" key={activity.id}><span className="activity-icon">{activity.event_type.includes("duplicate") ? "◈" : activity.event_type.includes("deleted") ? "−" : "+"}</span><div><b>{activity.message}</b><small>{activity.event_type} · {new Date(`${activity.created_at}Z`).toLocaleString()}</small></div></div>)}{!activities.length && <Empty text="No storage events recorded yet." />}</div></Panel></section>;
}

function StorageBars({ data, large = false }) {
  const maximum = Math.max(data.logical_storage, 1);
  return <div className={large ? "bars large" : "bars"}><div className="bar-row"><div><span>Logical storage</span><b>{formatBytes(data.logical_storage)}</b></div><div className="bar-track"><i style={{ width: `${data.logical_storage / maximum * 100}%` }} /></div></div><div className="bar-row"><div><span>Physical storage</span><b>{formatBytes(data.physical_storage)}</b></div><div className="bar-track purple"><i style={{ width: `${data.physical_storage / maximum * 100}%` }} /></div></div><div className="bar-row"><div><span>Storage saved</span><b className="text-positive">{formatBytes(data.storage_saved)}</b></div><div className="bar-track green"><i style={{ width: `${data.storage_saved / maximum * 100}%` }} /></div></div></div>;
}

function Panel({ title, action, onAction, children }) { return <div className="panel"><div className="panel-title"><h3>{title}</h3>{action && <button className="panel-action" onClick={onAction}>{action}</button>}</div>{children}</div>; }
function Metric({ label, value }) { return <div className="metric"><span>{label}</span><b>{value}</b></div>; }
function MetricCard({ label, value, tone = "" }) { return <div className={`metric-card ${tone}`}><span>{label}</span><strong>{value}</strong></div>; }
function Empty({ text }) { return <div className="empty">{text}</div>; }
function Loading() { return <div className="loading">Connecting to the storage API…</div>; }

createRoot(document.getElementById("root")).render(<App />);
