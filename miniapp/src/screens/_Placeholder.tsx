export default function Placeholder({ title, sub, note }: { title: string; sub: string; note: string }) {
  return (
    <>
      <div className="rise">
        <div className="title">{title}<small>{sub}</small></div>
        <div className="orn"><b>✦</b></div>
      </div>
      <div className="panel rise center" style={{ animationDelay: '.06s', padding: '34px 18px', flexDirection: 'column', gap: 10, textAlign: 'center' }}>
        <div style={{ fontSize: 38, filter: 'drop-shadow(0 2px 4px #000)' }}>🛠</div>
        <div className="flavor">{note}</div>
      </div>
    </>
  )
}
