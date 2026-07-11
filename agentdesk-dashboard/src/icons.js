/**
 * icons.js — Barrel centralizado de iconos Lucide para AgentDesk.
 *
 * Importar desde aquí en lugar de directamente de "lucide-react" garantiza
 * que Vite agrupe todos los iconos en un único chunk y PyInstaller los empaquete
 * sin errores de tree-shaking al generar el bundle de React.
 *
 * Uso:
 *   import { Shield, Users, RefreshCw } from "../../icons";
 */

export {
  // ── Acciones generales ──────────────────────────────────────────────────────
  Check,
  CheckCircle,
  CheckCircle2,
  Copy,
  Download,
  Edit,
  Edit2,
  ExternalLink,
  Filter,
  Maximize,
  Maximize2,
  Minimize,
  Minus,
  MoreHorizontal,
  MoreVertical,
  Plus,
  RefreshCw,
  Save,
  Search,
  Send,
  Share,
  Trash,
  Trash2,
  Upload,
  X,
  XCircle,
  ZoomIn,
  ZoomOut,

  // ── Navegación ──────────────────────────────────────────────────────────────
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ChevronsDown,
  ChevronsLeft,
  ChevronsRight,
  ChevronsUp,
  Home,
  Menu,

  // ── Estado y alertas ───────────────────────────────────────────────────────
  AlertCircle,
  AlertOctagon,
  AlertTriangle,
  Bell,
  BellOff,
  BellRing,
  Clock,
  Info,

  // ── Usuarios y seguridad ───────────────────────────────────────────────────
  Eye,
  EyeOff,
  Key,
  Lock,
  LogIn,
  LogOut,
  Shield,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  Unlock,
  User,
  UserCheck,
  UserMinus,
  UserPlus,
  UserX,
  Users,

  // ── Control de sistema ─────────────────────────────────────────────────────
  Power,
  PowerOff,
  Settings,
  Settings2,
  Sliders,
  SlidersHorizontal,
  ToggleLeft,
  ToggleRight,

  // ── Analítica y métricas ───────────────────────────────────────────────────
  Activity,
  BarChart,
  BarChart2,
  BarChart3,
  BarChart4,
  LineChart,
  PieChart,
  TrendingDown,
  TrendingUp,

  // ── Finanzas y proyectos ───────────────────────────────────────────────────
  Banknote,
  Calculator,
  Calendar,
  CalendarCheck,
  CalendarClock,
  CalendarDays,
  DollarSign,
  Target,

  // ── Infraestructura ────────────────────────────────────────────────────────
  Cloud,
  CloudOff,
  Cpu,
  Database,
  Globe,
  HardDrive,
  Network,
  Server,
  Wifi,
  WifiOff,

  // ── Archivos y documentos ──────────────────────────────────────────────────
  File,
  FileCheck,
  FileCode,
  FileJson,
  FileMinus,
  FilePlus,
  FileText,
  FileX,
  Folder,
  FolderOpen,

  // ── Comunicación ───────────────────────────────────────────────────────────
  Mail,
  MessageCircle,
  MessageSquare,

  // ── Agentes / IA ───────────────────────────────────────────────────────────
  Bot,
  Brain,
  Cpu as Chip,
  GitBranch,
  GitCommit,
  GitMerge,
  Play,
  PlayCircle,
  Repeat,
  Repeat2,
  Shuffle,
  Square,
  StopCircle,
  Zap,
  ZapOff,

  // ── Mapa y geografía ───────────────────────────────────────────────────────
  Compass,
  Map,
  MapPin,
  Navigation,

  // ── Miscelánea UI ─────────────────────────────────────────────────────────
  Bookmark,
  Briefcase,
  Circle,
  Columns,
  DivideCircle,
  Dot,
  GripVertical,
  Hash,
  Layers,
  Layout,
  LayoutDashboard,
  List,
  Package,
  Palette,
  Paperclip,
  Tag,
  Tags,
  Terminal,
  Timer,
  Tooltip,
} from "lucide-react";
