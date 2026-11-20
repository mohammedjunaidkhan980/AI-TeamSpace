import { Button } from "./button";
import { Modal } from "./modal";
import { Spinner } from "./spinner";

interface ConfirmationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel?: string;
  pending?: boolean;
  onConfirm: () => void;
}

export function ConfirmationDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  pending = false,
  onConfirm,
}: ConfirmationDialogProps) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} title={title} description={description}>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>Cancel</Button>
        <Button type="button" variant="danger" onClick={onConfirm} disabled={pending}>
          {pending && <Spinner />} {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
