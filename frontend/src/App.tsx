import { ChatReview } from "./pages/ChatReview";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";
import { MindMap } from "./pages/MindMap";
import { Outline } from "./pages/Outline";
import { Quiz } from "./pages/Quiz";
import { SubjectDetail } from "./pages/SubjectDetail";
import { UploadMaterial } from "./pages/UploadMaterial";

export function App() {
  return (
    <>
      <Login />
      <Dashboard />
      <SubjectDetail />
      <UploadMaterial />
      <ChatReview />
      <Outline />
      <Quiz />
      <MindMap />
    </>
  );
}
