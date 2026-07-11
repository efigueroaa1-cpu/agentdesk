import { ShieldOff } from "../../icons.js";

export default function AccessDenied({ mensaje }) {
  return (
    <div className="min-h-screen bg-gray-900 flex items-center justify-center p-4">
      <div className="text-center max-w-sm">
        <div className="w-16 h-16 bg-red-500/10 rounded-2xl mx-auto mb-4
                        flex items-center justify-center">
          <ShieldOff size={32} className="text-red-400" />
        </div>
        <h1 className="text-xl font-bold text-white mb-2">Acceso Denegado</h1>
        <p className="text-sm text-gray-400">
          {mensaje ?? "Aplicacion temporalmente bloqueada. Contacta al administrador."}
        </p>
      </div>
    </div>
  );
}
