export default function PitchAngles({ angles = [] }) {
  if (!angles.length) return null

  return (
    <div className="rounded-xl bg-yotpo-purple p-5">
      <h3 className="text-xs font-bold text-purple-300 uppercase tracking-widest mb-4">
        Top 3 Pitch Angles
      </h3>
      <div className="space-y-3">
        {angles.slice(0, 3).map((angle, i) => (
          <div key={i} className="flex gap-3">
            <span className="text-purple-300 font-black text-lg leading-tight flex-shrink-0 w-5">
              {i + 1}
            </span>
            <p className="text-white text-sm leading-relaxed">{angle}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
