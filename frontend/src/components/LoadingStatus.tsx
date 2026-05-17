type LoadingStatusProps = {
  message?: string;
};

export function LoadingStatus({ message = "Loading" }: LoadingStatusProps) {
  return <p aria-live="polite">{message}</p>;
}
