import { useOnboarding } from "../hooks/useOnboarding";
import ProgressBar from "../components/onboarding/ProgressBar";
import StepIdentity from "../components/onboarding/StepIdentity";
import StepInference from "../components/onboarding/StepInference";
import StepRooms from "../components/onboarding/StepRooms";
import StepReady from "../components/onboarding/StepReady";

interface Props {
  onComplete: () => void;
}

export default function Onboarding({ onComplete }: Props) {
  const ob = useOnboarding();

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-[#E0E0E0] flex items-center justify-center p-4">
      <div className="w-full max-w-xl">
        <div className="mb-8 text-center">
          <h1 className="text-2xl text-white font-bold tracking-wide phosphor-glow">oikOS</h1>
          <p className="text-neutral-600 text-sm">The OS for your AI.</p>
        </div>

        <ProgressBar current={ob.step} />

        {ob.step === 0 && (
          <StepIdentity
            name={ob.name}
            setName={ob.setName}
            description={ob.description}
            setDescription={ob.setDescription}
            onNext={ob.next}
          />
        )}

        {ob.step === 1 && (
          <StepInference
            backends={ob.backends}
            setBackends={ob.setBackends}
            selectedModel={ob.selectedModel}
            setSelectedModel={ob.setSelectedModel}
            configuredProviders={ob.configuredProviders}
            setConfiguredProviders={ob.setConfiguredProviders}
            onNext={ob.next}
            onBack={ob.back}
          />
        )}

        {ob.step === 2 && (
          <StepRooms
            selectedRoom={ob.selectedRoom}
            setSelectedRoom={ob.setSelectedRoom}
            onNext={ob.next}
            onBack={ob.back}
          />
        )}

        {ob.step === 3 && (
          <StepReady
            selectedModel={ob.selectedModel}
            configuredProviders={ob.configuredProviders}
            selectedRoom={ob.selectedRoom}
            onComplete={onComplete}
          />
        )}
      </div>
    </div>
  );
}
